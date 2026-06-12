"""单篇文献 AI 摘要提取 API.

路由: POST /api/v1/literature/{paper_id}/extract
使用 Kimi API JSON Mode 从全文提取结构化摘要，SSE 流式响应。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.config import DEFAULT_MODEL, DEFAULT_TEMPERATURE, MAX_RETRIES, RETRY_BASE_DELAY
from backend.models.schemas import PaperParseResponse
from backend.models.tables import ExtractedData, Paper, PaperPage, PaperStatus
from backend.services.db import SessionLocal
from backend.services.extract_prompt import build_extract_prompt
from backend.services.kimi_client import KimiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/literature", tags=["extract"])

# 提取最大 token 数（JSON Mode 需要足够输出空间）
_EXTRACT_MAX_TOKENS = 4096

# 按 paper_id 的互斥锁（防止同一文献并发重复提取）
_extract_locks: dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_full_text(db: Session, paper_id: str) -> str:
    """拼接文献所有页面的文本."""
    pages = (
        db.query(PaperPage)
        .filter(PaperPage.paper_id == paper_id)
        .order_by(PaperPage.page_number)
        .all()
    )
    parts: list[str] = []
    for p in pages:
        if p.text_content:
            parts.append(p.text_content)
    return "\n\n".join(parts)


def _parse_extracted_json(raw_json: str) -> dict:
    """从 Kimi JSON Mode 返回的字符串中解析 JSON.

    处理常见的格式问题：前后空格、markdown 代码块包裹。
    """
    text = raw_json.strip()
    # 移除可能的 markdown 代码块标记
    if text.startswith("```"):
        # 找到第一个换行后和最后一个 ``` 之前
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取第一个 { 到最后一个 } 之间的内容
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                raise ValueError("AI 返回内容无法解析为 JSON，请重试")
        else:
            raise ValueError("AI 返回内容无法解析为 JSON，请重试")

    if not isinstance(data, dict):
        raise ValueError("AI 返回的 JSON 格式不正确")

    return data


def _save_extracted_data(
    db: Session,
    paper_id: str,
    data: dict,
) -> ExtractedData:
    """将提取结果存入 extracted_data 表（upsert 逻辑）."""
    existing = (
        db.query(ExtractedData)
        .filter(ExtractedData.paper_id == paper_id)
        .first()
    )
    if existing:
        existing.research_question = data.get("research_question", "")
        existing.sample_source = data.get("sample_source", "")
        existing.sample_size = data.get("sample_size", "")
        existing.key_methods = data.get("key_methods", [])
        existing.key_data = data.get("key_data", [])
        existing.limitations = data.get("limitations", [])
        existing.background = data.get("background", "")
        existing.methods = data.get("methods", "")
        existing.key_results = data.get("key_results", [])
        existing.conclusion = data.get("conclusion", "")
        existing.keywords = data.get("keywords", [])
        existing.raw_json = data
        existing.translation = None
        existing.extracted_at = datetime.utcnow()
        return existing
    else:
        record = ExtractedData(
            id=str(uuid.uuid4()),
            paper_id=paper_id,
            research_question=data.get("research_question", ""),
            sample_source=data.get("sample_source", ""),
            sample_size=data.get("sample_size", ""),
            key_methods=data.get("key_methods", []),
            key_data=data.get("key_data", []),
            limitations=data.get("limitations", []),
            background=data.get("background", ""),
            methods=data.get("methods", ""),
            key_results=data.get("key_results", []),
            conclusion=data.get("conclusion", ""),
            keywords=data.get("keywords", []),
            raw_json=data,
            translation=None,
            extracted_at=datetime.utcnow(),
        )
        db.add(record)
        return record


# ---------------------------------------------------------------------------
# SSE 事件构建
# ---------------------------------------------------------------------------


def _sse_msg(data: dict) -> str:
    """构建 SSE data 行."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# POST /{paper_id}/extract
# ---------------------------------------------------------------------------


@router.post("/{paper_id}/extract")
async def extract_paper(paper_id: str, request: Request):
    """单篇文献 AI 摘要提取（SSE 流式响应）.

    流程：
    1. 校验文献存在、非扫描版、非提取中/已锁定
    2. 拼接 paper_pages 全文
    3. Kimi JSON Mode 提取结构化摘要（3 次指数退避重试）
    4. 同一事务内完成：状态变更 → 保存 → commit
    5. SSE 流式返回进度，客户端断开时回退状态
    """
    # ── 并发互斥锁 ──
    lock = _extract_locks.setdefault(paper_id, asyncio.Lock())

    async with lock:
        return await _do_extract(paper_id, request)


async def _do_extract(paper_id: str, request: Request) -> StreamingResponse:
    """在互斥锁内执行提取（核心逻辑）."""
    db = SessionLocal()

    try:
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise HTTPException(status_code=404, detail="文献不存在")

        # 扫描版直接跳过
        if paper.is_scanned:
            raise HTTPException(
                status_code=400,
                detail="检测到扫描版 PDF，无法自动提取摘要。请手动输入。",
            )

        # 并发提取互斥检查
        if paper.status == PaperStatus.EXTRACTING.value:
            raise HTTPException(status_code=409, detail="该文献正在提取中，请稍后再试")

        if paper.status == PaperStatus.EXTRACT_FAILED.value:
            raise HTTPException(
                status_code=400,
                detail="该文献已提取失败（已达最大重试次数），请先手动重置后再试",
            )

        # 拼接全文
        full_text = _get_full_text(db, paper_id)
        if not full_text.strip():
            raise HTTPException(
                status_code=400,
                detail="文献全文为空，无法提取摘要。可能是 PDF 解析失败。",
            )

        prompt = build_extract_prompt(full_text)

        # 状态 → extracting（同一 Session，后续一次性 commit）
        paper.status = PaperStatus.EXTRACTING.value
        paper.extraction_attempts = (paper.extraction_attempts or 0) + 1
        paper.last_error = None
        db.commit()

        attempts = paper.extraction_attempts

    finally:
        db.close()

    async def event_generator():
        """SSE 事件生成器."""
        yield _sse_msg({
            "type": "status",
            "status": "extracting",
            "attempt": attempts,
            "max_retries": MAX_RETRIES,
        })

        # ── 调用 Kimi JSON Mode（指数退避重试，对齐 kimi_client.py）──
        full_response = ""
        extract_ok = False
        last_error: Optional[Exception] = None
        client = KimiClient()

        for retry_attempt in range(MAX_RETRIES + 1):
            if await request.is_disconnected():
                # 客户端断开 → 回退状态
                _rollback_extracting(paper_id)
                yield _sse_msg({"type": "cancelled", "message": "客户端已断开"})
                yield _sse_msg({"type": "done"})
                return

            try:
                completion = await client._client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=DEFAULT_TEMPERATURE,
                    max_tokens=_EXTRACT_MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
                full_response = completion.choices[0].message.content or ""
                yield _sse_msg({
                    "type": "chunk",
                    "content": full_response,
                })
                extract_ok = True
                break
            except Exception as exc:
                last_error = exc
                if retry_attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** retry_attempt)
                    logger.warning(
                        "提取 API 失败 paper_id=%s (尝试 %d/%d)，%0.1fs 后重试: %s",
                        paper_id, retry_attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    yield _sse_msg({
                        "type": "retry",
                        "attempt": retry_attempt + 1,
                        "max_retries": MAX_RETRIES,
                        "delay": delay,
                    })
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "提取失败 paper_id=%s，已用尽 %d 次重试: %s",
                        paper_id, MAX_RETRIES + 1, exc,
                    )

        # ── 失败处理 ──
        if not extract_ok:
            db_fail = SessionLocal()
            try:
                p = db_fail.query(Paper).filter(Paper.id == paper_id).first()
                if p:
                    if attempts >= MAX_RETRIES:
                        p.status = PaperStatus.EXTRACT_FAILED.value
                        p.last_error = f"已重试 {MAX_RETRIES} 次均失败: {str(last_error)[:500]}" if last_error else "未知错误"
                    else:
                        p.status = PaperStatus.PENDING.value
                        p.last_error = str(last_error)[:500] if last_error else "未知错误"
                    db_fail.commit()
            finally:
                db_fail.close()

            yield _sse_msg({
                "type": "error",
                "code": "EXTRACT_FAILED",
                "message": f"提取失败: {str(last_error)[:200]}" if last_error else "未知错误",
                "attempt": attempts,
            })
            yield _sse_msg({"type": "done"})
            return

        # ── 解析 JSON ──
        try:
            extracted = _parse_extracted_json(full_response)
        except ValueError as e:
            logger.warning("JSON 解析失败 paper_id=%s: %s", paper_id, e)
            db_fail2 = SessionLocal()
            try:
                p = db_fail2.query(Paper).filter(Paper.id == paper_id).first()
                if p:
                    if attempts >= MAX_RETRIES:
                        p.status = PaperStatus.EXTRACT_FAILED.value
                        p.last_error = f"JSON 解析失败: {str(e)}"
                    else:
                        p.status = PaperStatus.PENDING.value
                        p.last_error = f"JSON 解析失败: {str(e)}"
                    db_fail2.commit()
            finally:
                db_fail2.close()

            yield _sse_msg({
                "type": "error",
                "code": "EXTRACT_JSON_PARSE_ERROR",
                "message": str(e),
                "attempt": attempts,
            })
            yield _sse_msg({"type": "done"})
            return

        # ── 保存结果（同一事务：状态 + extracted_data + 元数据 → 一次 commit）──
        db_save = SessionLocal()
        try:
            p = db_save.query(Paper).filter(Paper.id == paper_id).first()
            if not p:
                yield _sse_msg({"type": "error", "code": "NOT_FOUND", "message": "文献已不存在"})
                yield _sse_msg({"type": "done"})
                return

            p.status = PaperStatus.COMPLETED.value
            p.extracted_at = datetime.utcnow()
            p.last_error = None

            if extracted.get("title") and not p.title:
                p.title = extracted["title"]
            if extracted.get("authors") and not p.authors:
                p.authors = extracted["authors"]
            if extracted.get("year") and not p.year:
                p.year = extracted["year"]
            if extracted.get("journal") and not p.journal:
                p.journal = extracted["journal"]

            _save_extracted_data(db_save, paper_id, extracted)
            db_save.commit()
        finally:
            db_save.close()

        yield _sse_msg({
            "type": "result",
            "paper_id": paper_id,
            "title": extracted.get("title", ""),
            "keywords": extracted.get("keywords", []),
        })
        yield _sse_msg({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _rollback_extracting(paper_id: str) -> None:
    """客户端断开时将 extracting 状态回退为 pending."""
    db = SessionLocal()
    try:
        p = db.query(Paper).filter(Paper.id == paper_id).first()
        if p and p.status == PaperStatus.EXTRACTING.value:
            p.status = PaperStatus.PENDING.value
            p.last_error = "客户端断开连接，提取中断"
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


__all__ = ["router"]
