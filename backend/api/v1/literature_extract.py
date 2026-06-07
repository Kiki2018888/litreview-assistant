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

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.config import DEFAULT_MODEL, DEFAULT_TEMPERATURE, MAX_RETRIES
from backend.models.schemas import PaperParseResponse
from backend.models.tables import ExtractedData, Paper, PaperPage, PaperStatus
from backend.services.db import SessionLocal
from backend.services.extract_prompt import build_extract_prompt
from backend.services.kimi_client import KimiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/literature", tags=["extract"])

# 提取最大 token 数（JSON Mode 需要足够输出空间）
_EXTRACT_MAX_TOKENS = 4096


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
async def extract_paper(paper_id: str):
    """单篇文献 AI 摘要提取（SSE 流式响应）.

    流程：
    1. 校验文献存在且非扫描版
    2. 拼接 paper_pages 全文
    3. Kimi JSON Mode 提取结构化摘要
    4. 流式返回进度 → 结果 → 存入 extracted_data
    5. 状态变更：pending → extracting → completed / extract_failed
    6. 失败最多重试 MAX_RETRIES 次，全部失败后锁定
    """
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

        # 拼接全文
        full_text = _get_full_text(db, paper_id)
        if not full_text.strip():
            raise HTTPException(
                status_code=400,
                detail="文献全文为空，无法提取摘要。可能是 PDF 解析失败。",
            )

        # 构建 Prompt
        prompt = build_extract_prompt(full_text)

    finally:
        db.close()

    async def event_generator():
        """SSE 事件生成器 — 在独立线程中调用 Kimi API."""
        # 状态 → extracting
        db_status = SessionLocal()
        try:
            paper_obj = db_status.query(Paper).filter(Paper.id == paper_id).first()
            if paper_obj:
                paper_obj.status = PaperStatus.EXTRACTING.value
                paper_obj.extraction_attempts = (paper_obj.extraction_attempts or 0) + 1
                paper_obj.last_error = None
                db_status.commit()

            attempts = paper_obj.extraction_attempts if paper_obj else 0
            yield _sse_msg( {
                "type": "status",
                "status": "extracting",
                "attempt": attempts,
                "max_retries": MAX_RETRIES,
            })
        finally:
            db_status.close()

        # 调用 Kimi JSON Mode
        full_response = ""
        client = KimiClient()

        try:
            stream = await client._client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=_EXTRACT_MAX_TOKENS,
                stream=True,
                response_format={"type": "json_object"},
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    full_response += delta.content
                    yield _sse_msg( {
                        "type": "chunk",
                        "content": delta.content,
                    })

        except Exception as exc:
            logger.error("提取失败 paper_id=%s, attempt=%d: %s", paper_id, attempts, exc)
            # 更新状态
            db_fail = SessionLocal()
            try:
                p = db_fail.query(Paper).filter(Paper.id == paper_id).first()
                if p:
                    if attempts >= MAX_RETRIES:
                        p.status = PaperStatus.EXTRACT_FAILED.value
                        p.last_error = f"已重试 {MAX_RETRIES} 次均失败: {str(exc)[:500]}"
                    else:
                        p.status = PaperStatus.PENDING.value
                        p.last_error = str(exc)[:500]
                    db_fail.commit()
            finally:
                db_fail.close()

            yield _sse_msg( {
                "type": "error",
                "code": "EXTRACT_FAILED",
                "message": f"提取失败: {str(exc)[:200]}",
                "attempt": attempts,
            })
            yield _sse_msg( {"type": "done"})
            return

        # 解析 JSON 结果
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

            yield _sse_msg( {
                "type": "error",
                "code": "EXTRACT_JSON_PARSE_ERROR",
                "message": str(e),
                "attempt": attempts,
            })
            yield _sse_msg( {"type": "done"})
            return

        # 保存结果
        db_save = SessionLocal()
        try:
            p = db_save.query(Paper).filter(Paper.id == paper_id).first()
            if p:
                p.status = PaperStatus.COMPLETED.value
                p.extracted_at = datetime.utcnow()
                p.last_error = None
            _save_extracted_data(db_save, paper_id, extracted)

            # 同步更新 paper 元数据（如果 AI 提取的更好）
            if p:
                if extracted.get("title") and not p.title:
                    p.title = extracted["title"]
                if extracted.get("authors") and not p.authors:
                    p.authors = extracted["authors"]
                if extracted.get("year") and not p.year:
                    p.year = extracted["year"]
                if extracted.get("journal") and not p.journal:
                    p.journal = extracted["journal"]

            db_save.commit()
        finally:
            db_save.close()

        # 发送完成结果
        yield _sse_msg( {
            "type": "result",
            "paper_id": paper_id,
            "title": extracted.get("title", ""),
            "keywords": extracted.get("keywords", []),
        })
        yield _sse_msg( {"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["router"]
