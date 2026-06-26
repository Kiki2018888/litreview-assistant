"""批量 AI 摘要提取逻辑（SSE 流）.

v1.1.0: 路由挂载在 POST /api/v1/projects/{id}/batch-extract。
原 /api/v1/batches/batch-extract 已废弃。

ADR-2: 每篇文献独立走 parse_and_validate + 修复循环。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import AsyncIterator, Optional

from fastapi import HTTPException, Request
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from backend.config import (
    BATCH_EXTRACT_CONCURRENCY,
    DEFAULT_TEMPERATURE,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)
from backend.models.tables import ExtractedData, Paper, PaperPage, PaperStatus, Project
from backend.services.db import SessionLocal
from backend.services.extract_prompt import build_extract_prompt
from backend.api.v1.literature_extract import (
    _is_retryable_error,
    _retry_after_seconds,
)
from backend.services.extract_service import (
    ExtractQualityError,
    JSONParseError,
    ParseResult,
    _MAX_REPAIR_ATTEMPTS,
    _extract_validation_errors,
    build_repair_prompt,
    parse_and_validate,
)
from backend.services.kimi_client import KimiClient

logger = logging.getLogger(__name__)

_EXTRACT_MAX_TOKENS = 4096
_BATCH_INTERVAL = 1.0


def _get_full_text(db: Session, paper_id: str) -> str:
    pages = (
        db.query(PaperPage)
        .filter(PaperPage.paper_id == paper_id)
        .order_by(PaperPage.page_number)
        .all()
    )
    return "\n\n".join(p.text_content for p in pages if p.text_content)


def _save_extracted(db: Session, paper_id: str, parse_result: ParseResult) -> None:
    data = parse_result.data
    existing = db.query(ExtractedData).filter(ExtractedData.paper_id == paper_id).first()
    fields = {
        "research_question": data.get("research_question", ""),
        "sample_source": data.get("sample_source", ""),
        "sample_size": data.get("sample_size", ""),
        "key_methods": data.get("key_methods", []),
        "key_data": data.get("key_data", []),
        "limitations": data.get("limitations", []),
        "background": data.get("background", ""),
        "methods": data.get("methods", ""),
        "key_results": data.get("key_results", []),
        "conclusion": data.get("conclusion", ""),
        "keywords": data.get("keywords", []),
        "raw_json": data,
        "extracted_at": datetime.utcnow(),
    }
    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
    else:
        db.add(ExtractedData(id=str(uuid.uuid4()), paper_id=paper_id, **fields))


def _sse_msg(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _load_pending_papers(project_id: Optional[str]) -> tuple[list[Paper], int]:
    db = SessionLocal()
    try:
        if project_id:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise HTTPException(status_code=404, detail="项目不存在")
            papers = (
                db.query(Paper)
                .filter(
                    Paper.project_id == project_id,
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
        return papers, len(papers)
    finally:
        db.close()


async def _extract_one_paper(
    client: KimiClient,
    paper: Paper,
    idx: int,
    total: int,
    queue: "asyncio.Queue",
) -> None:
    """并发处理单篇文献：AI 提取 + 解析修复 + 写库，进度事件推入 queue."""
    paper_id = paper.id
    display_title = paper.title or paper_id[:8]

    try:
        await _extract_one_paper_inner(client, paper, idx, total, queue, paper_id, display_title)
    except asyncio.CancelledError:
        with SessionLocal() as db_f:
            p = db_f.query(Paper).filter(Paper.id == paper_id).first()
            if p and p.status == PaperStatus.EXTRACTING.value:
                p.status = PaperStatus.PENDING.value
                p.last_error = "批提取任务被取消，可重提"
                db_f.commit()
        raise
    finally:
        with SessionLocal() as db_f:
            p = db_f.query(Paper).filter(Paper.id == paper_id).first()
            if p and p.status == PaperStatus.EXTRACTING.value:
                p.status = PaperStatus.PENDING.value
                p.last_error = "批提取中断，可重提"
                db_f.commit()


async def _extract_one_paper_inner(
    client: KimiClient,
    paper: Paper,
    idx: int,
    total: int,
    queue: "asyncio.Queue",
    paper_id: str,
    display_title: str,
) -> None:
    # ── 读全文 ──
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
                # 不锁死：全文为空也回退 pending 可重提
                p.status = PaperStatus.PENDING.value
                p.last_error = "全文为空，无法提取（可重提）"
                db_f1.commit()
        finally:
            db_f1.close()
        await queue.put({
            "_final": True, "type": "progress", "current": idx, "total": total,
            "paper_id": paper_id, "status": "failed", "title": display_title,
            "error": "全文为空",
        })
        return

    prompt = build_extract_prompt(full_text)

    # ── 置 extracting + attempts++ ──
    db_st = SessionLocal()
    try:
        p = db_st.query(Paper).filter(Paper.id == paper_id).first()
        if p:
            p.status = PaperStatus.EXTRACTING.value
            p.extraction_attempts = (p.extraction_attempts or 0) + 1
            p.last_error = None
            db_st.commit()
    finally:
        db_st.close()

    await queue.put({
        "type": "progress", "current": idx, "total": total,
        "paper_id": paper_id, "status": "extracting", "title": display_title,
    })

    # ── AI 调用（退避重试 + 错误分类）──
    full_response = ""
    extract_ok = False
    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            completion = await client._client.chat.completions.create(
                model=client._model,
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
            retryable = _is_retryable_error(exc)
            if retryable and attempt < MAX_RETRIES:
                delay = _retry_after_seconds(exc, RETRY_BASE_DELAY * (2 ** attempt))
                await asyncio.sleep(delay)
            else:
                if not retryable:
                    logger.error("批提取遇不可重试错误 paper_id=%s: %s", paper_id, exc)
                else:
                    logger.error(
                        "批提取失败 paper_id=%s，已用尽 %d 次重试: %s",
                        paper_id, MAX_RETRIES + 1, exc,
                    )
                break

    if not extract_ok and last_error:
        full_response = str(last_error)

    # ── 解析 + 修复循环 ──
    parse_result = None
    repair_errors: list[str] = []
    if extract_ok:
        try:
            parse_result = parse_and_validate(full_response)
        except (JSONParseError, ExtractQualityError, PydanticValidationError) as e:
            repair_errors = _extract_validation_errors(e)

        repair_attempt = 0
        while parse_result is None and repair_attempt < _MAX_REPAIR_ATTEMPTS:
            repair_attempt += 1
            repair_prompt = build_repair_prompt(full_text, repair_errors)
            try:
                completion = await client._client.chat.completions.create(
                    model=client._model,
                    messages=[{"role": "user", "content": repair_prompt}],
                    temperature=DEFAULT_TEMPERATURE,
                    max_tokens=_EXTRACT_MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
                repair_response = completion.choices[0].message.content or ""
            except Exception:
                continue
            try:
                parse_result = parse_and_validate(repair_response)
            except (JSONParseError, ExtractQualityError, PydanticValidationError) as e:
                repair_errors = _extract_validation_errors(e)

    # ── 写库（独立短事务）──
    db_res = SessionLocal()
    try:
        p = db_res.query(Paper).filter(Paper.id == paper_id).first()
        if not p:
            await queue.put({
                "_final": True, "type": "progress", "current": idx, "total": total,
                "paper_id": paper_id, "status": "failed", "title": display_title,
                "error": "文献已不存在",
            })
            return

        if parse_result is not None:
            extracted = parse_result.data
            p.status = PaperStatus.COMPLETED.value
            p.extracted_at = datetime.utcnow()
            if parse_result.partial:
                p.last_error = "部分成功：缺失字段 " + ", ".join(parse_result.missing_fields)
            else:
                p.last_error = None
            _save_extracted(db_res, paper_id, parse_result)
            if extracted.get("title") and not p.title:
                p.title = extracted["title"]
            if extracted.get("authors") and not p.authors:
                p.authors = extracted["authors"]
            if extracted.get("year") and not p.year:
                p.year = extracted["year"]
            if extracted.get("journal") and not p.journal:
                p.journal = extracted["journal"]
            db_res.commit()
            await queue.put({
                "_final": True, "type": "progress", "current": idx, "total": total,
                "paper_id": paper_id, "status": "completed", "title": display_title,
                "partial": parse_result.partial,
            })
        else:
            # 不锁死：批量失败统一回退 pending 可直接重提
            if extract_ok and repair_errors:
                p.status = PaperStatus.PENDING.value
                p.last_error = ("解析失败（可重提）: " + "; ".join(repair_errors[:5]))[:500]
            else:
                p.status = PaperStatus.PENDING.value
                p.last_error = (
                    f"调用失败（可重提）: {full_response}" if full_response else "未知错误"
                )[:500]
            db_res.commit()
            await queue.put({
                "_final": True, "type": "progress", "current": idx, "total": total,
                "paper_id": paper_id, "status": "failed", "title": display_title,
                "error": (p.last_error or "未知错误")[:200],
            })
    finally:
        db_res.close()


async def stream_project_batch_extract(
    project_id: str,
    request: Request,
) -> AsyncIterator[str]:
    """按项目批量提取 pending 文献，SSE 事件流（保守并发版）."""
    try:
        papers, total = _load_pending_papers(project_id)
    except HTTPException as exc:
        yield _sse_msg({"type": "error", "message": exc.detail})
        return

    if total == 0:
        yield _sse_msg({
            "type": "done",
            "success_count": 0,
            "fail_count": 0,
            "message": "没有待处理的文献",
        })
        return

    success_count = 0
    fail_count = 0
    client = KimiClient()

    # 保守并发：上限 = min(配置并发, 篇数)，多路并行 AI 调用、独立短事务写库
    concurrency = max(1, min(BATCH_EXTRACT_CONCURRENCY, total))
    sem = asyncio.Semaphore(concurrency)
    queue: asyncio.Queue = asyncio.Queue()
    cancelled = asyncio.Event()
    logger.info("批量提取启动：%d 篇，并发 %d", total, concurrency)

    async def _runner(idx: int, paper: Paper) -> None:
        async with sem:
            if cancelled.is_set():
                await queue.put({
                    "_final": True, "type": "progress", "current": idx, "total": total,
                    "paper_id": paper.id, "status": "skipped",
                    "title": paper.title or paper.id[:8],
                })
                return
            await _extract_one_paper(client, paper, idx, total, queue)

    tasks = [
        asyncio.create_task(_runner(i, p))
        for i, p in enumerate(papers, start=1)
    ]

    try:
        remaining = total
        while remaining > 0:
            if await request.is_disconnected():
                logger.info("批提取客户端断开，取消剩余任务")
                cancelled.set()
                break
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            is_final = ev.pop("_final", False)
            yield _sse_msg(ev)
            if is_final:
                remaining -= 1
                if ev.get("status") == "completed":
                    success_count += 1
                elif ev.get("status") == "failed":
                    fail_count += 1
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    yield _sse_msg({
        "type": "done",
        "success_count": success_count,
        "fail_count": fail_count,
    })


__all__ = ["stream_project_batch_extract"]
