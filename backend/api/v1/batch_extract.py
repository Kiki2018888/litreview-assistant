"""批量 AI 摘要提取 API.

路由: POST /api/v1/batches/batch-extract
获取批次中所有 pending 文献，串行执行提取，SSE 进度流。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse

from backend.config import DEFAULT_MODEL, DEFAULT_TEMPERATURE, MAX_RETRIES, RETRY_BASE_DELAY
from backend.models.tables import Batch, ExtractedData, Paper, PaperPage, PaperStatus
from backend.services.db import SessionLocal
from backend.services.extract_prompt import build_extract_prompt
from backend.services.kimi_client import KimiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/batches", tags=["batch-extract"])

_EXTRACT_MAX_TOKENS = 4096
_BATCH_INTERVAL = 1.0  # 篇间间隔，秒


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------


class BatchExtractRequest(BaseModel):
    """批量提取请求."""

    batch_id: Optional[str] = Field(None, description="批次 ID（可选，不传则提取全局所有 pending 文献）")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_full_text(db: Session, paper_id: str) -> str:
    """拼接文献所有页面文本."""
    pages = (
        db.query(PaperPage)
        .filter(PaperPage.paper_id == paper_id)
        .order_by(PaperPage.page_number)
        .all()
    )
    return "\n\n".join(p.text_content for p in pages if p.text_content)


def _parse_extracted_json(raw_json: str) -> dict:
    """从 Kimi JSON 返回解析 JSON."""
    import json as _json
    text = raw_json.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            data = _json.loads(text[start : end + 1])
        else:
            raise ValueError("AI 返回无法解析为 JSON")
    if not isinstance(data, dict):
        raise ValueError("AI 返回 JSON 格式不正确")
    return data


def _save_extracted(db: Session, paper_id: str, data: dict) -> None:
    """Upsert 提取结果."""
    existing = (
        db.query(ExtractedData).filter(ExtractedData.paper_id == paper_id).first()
    )
    if existing:
        existing.background = data.get("background", "")
        existing.methods = data.get("methods", "")
        existing.key_results = data.get("key_results", [])
        existing.conclusion = data.get("conclusion", "")
        existing.keywords = data.get("keywords", [])
        existing.raw_json = data
        existing.extracted_at = datetime.utcnow()
    else:
        db.add(ExtractedData(
            id=str(uuid.uuid4()),
            paper_id=paper_id,
            background=data.get("background", ""),
            methods=data.get("methods", ""),
            key_results=data.get("key_results", []),
            conclusion=data.get("conclusion", ""),
            keywords=data.get("keywords", []),
            raw_json=data,
            extracted_at=datetime.utcnow(),
        ))


def _sse_msg(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# POST /batch-extract
# ---------------------------------------------------------------------------


@router.post("/batch-extract")
async def batch_extract(body: BatchExtractRequest, request: Request):
    """批量 AI 摘要提取（SSE 进度流）.

    - 有 batch_id 时仅提取该批次 pending 文献
    - 无 batch_id 时提取全局所有 pending 文献
    - 串行提取，篇间隔 ≥ 1 秒，支持客户端断开检测
    """
    db = SessionLocal()
    try:
        if body.batch_id:
            batch = db.query(Batch).filter(Batch.id == body.batch_id).first()
            if not batch:
                raise HTTPException(status_code=404, detail="批次不存在")
            papers = (
                db.query(Paper)
                .filter(
                    Paper.batch_id == body.batch_id,
                    Paper.status == PaperStatus.PENDING.value,
                    Paper.is_scanned == False,  # noqa: E712
                )
                .order_by(Paper.created_at)
                .all()
            )
        else:
            papers = (
                db.query(Paper)
                .filter(
                    Paper.status == PaperStatus.PENDING.value,
                    Paper.is_scanned == False,  # noqa: E712
                )
                .order_by(Paper.created_at)
                .all()
            )
        total = len(papers)
    finally:
        db.close()

    if total == 0:
        async def empty_gen():
            yield _sse_msg({
                "type": "done",
                "success_count": 0,
                "fail_count": 0,
                "message": "没有待处理的文献",
            })
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    async def event_generator():
        success_count = 0
        fail_count = 0
        client = KimiClient()

        for idx, paper in enumerate(papers, start=1):
            # ── 客户端断开检测 ──
            if await request.is_disconnected():
                logger.info("批提取客户端断开，已处理 %d/%d", idx - 1, total)
                break

            paper_id = paper.id
            display_title = paper.title or paper_id[:8]

            # ── 拼接全文 ──
            db_text = SessionLocal()
            try:
                full_text = _get_full_text(db_text, paper_id)
            finally:
                db_text.close()

            if not full_text.strip():
                db_f1 = SessionLocal()
                try:
                    p = db_f1.query(Paper).filter(Paper.id == paper_id).first()
                    if p:
                        p.status = PaperStatus.FAILED.value
                        p.last_error = "全文为空，无法提取"
                        db_f1.commit()
                finally:
                    db_f1.close()

                fail_count += 1
                yield _sse_msg({
                    "type": "progress",
                    "current": idx,
                    "total": total,
                    "paper_id": paper_id,
                    "status": "failed",
                    "title": display_title,
                    "error": "全文为空",
                })
                await asyncio.sleep(_BATCH_INTERVAL)
                continue

            prompt = build_extract_prompt(full_text)

            # ── 设置 extracting ──
            db_st = SessionLocal()
            try:
                p = db_st.query(Paper).filter(Paper.id == paper_id).first()
                if p:
                    p.status = PaperStatus.EXTRACTING.value
                    p.extraction_attempts = (p.extraction_attempts or 0) + 1
                    p.last_error = None
                    db_st.commit()
                attempts = p.extraction_attempts if p else 0
            finally:
                db_st.close()

            if await request.is_disconnected():
                break

            yield _sse_msg({
                "type": "progress",
                "current": idx,
                "total": total,
                "paper_id": paper_id,
                "status": "extracting",
                "title": display_title,
            })

            # ── 调用 Kimi JSON Mode（带指数退避重试，对齐 kimi_client.py）──
            full_response = ""
            extract_ok = False
            last_error: Optional[Exception] = None

            for attempt in range(MAX_RETRIES + 1):
                if await request.is_disconnected():
                    break
                try:
                    completion = await client._client.chat.completions.create(
                        model=DEFAULT_MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=DEFAULT_TEMPERATURE,
                        max_tokens=_EXTRACT_MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
                    full_response = completion.choices[0].message.content or ""
                    extract_ok = True
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < MAX_RETRIES:
                        delay = RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "批提取 API 失败 paper_id=%s (尝试 %d/%d)，%0.1fs 后重试: %s",
                            paper_id, attempt + 1, MAX_RETRIES + 1, delay, exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "批提取失败 paper_id=%s，已用尽 %d 次重试: %s",
                            paper_id, MAX_RETRIES + 1, exc,
                        )

            if not extract_ok and last_error:
                full_response = str(last_error)

            # ── 解析 JSON ──
            if extract_ok:
                try:
                    extracted = _parse_extracted_json(full_response)
                except ValueError as e:
                    extract_ok = False
                    full_response = str(e)

            # ── 持久化结果 ──
            db_res = SessionLocal()
            try:
                p = db_res.query(Paper).filter(Paper.id == paper_id).first()
                if not p:
                    continue

                if extract_ok:
                    p.status = PaperStatus.COMPLETED.value
                    p.extracted_at = datetime.utcnow()
                    p.last_error = None
                    _save_extracted(db_res, paper_id, extracted)
                    if extracted.get("title") and not p.title:
                        p.title = extracted["title"]
                    if extracted.get("authors") and not p.authors:
                        p.authors = extracted["authors"]
                    if extracted.get("year") and not p.year:
                        p.year = extracted["year"]
                    if extracted.get("journal") and not p.journal:
                        p.journal = extracted["journal"]
                    db_res.commit()
                    success_count += 1
                    yield _sse_msg({
                        "type": "progress",
                        "current": idx,
                        "total": total,
                        "paper_id": paper_id,
                        "status": "completed",
                        "title": display_title,
                    })
                else:
                    attempts = p.extraction_attempts or 0
                    if attempts >= MAX_RETRIES:
                        p.status = PaperStatus.EXTRACT_FAILED.value
                    else:
                        p.status = PaperStatus.PENDING.value
                    p.last_error = (full_response or "未知错误")[:500]
                    db_res.commit()
                    fail_count += 1
                    yield _sse_msg({
                        "type": "progress",
                        "current": idx,
                        "total": total,
                        "paper_id": paper_id,
                        "status": "failed",
                        "title": display_title,
                        "error": p.last_error[:200],
                    })
            finally:
                db_res.close()

            # 篇间间隔
            await asyncio.sleep(_BATCH_INTERVAL)

        # ── done ──
        yield _sse_msg({
            "type": "done",
            "success_count": success_count,
            "fail_count": fail_count,
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["router"]
