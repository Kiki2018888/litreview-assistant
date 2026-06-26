"""后台抽取 Job Worker（claims + 摘要）.

后台 asyncio 任务：
- 轮询 queued 的 claims_extract / summary_extract Job
- 按 paper 边界逐篇处理，独立短事务写库
- cancel/pause 在 paper 边界检查 job.status
- 通过 asyncio.Queue 向 SSE 订阅者广播进度事件
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from backend.config import DEFAULT_TEMPERATURE, MAX_RETRIES, RETRY_BASE_DELAY
from backend.models.tables import (
    Claim,
    ExtractedData,
    ExtractJob,
    JobStatus,
    JobType,
    Paper,
    PaperPage,
    PaperStatus,
    Project,
)
from backend.services.claim_extract_prompt import normalize_text
from backend.services.claim_extractor import (
    PageBlock,
    extract_claims_for_paper,
)
from backend.services.db import SessionLocal
from backend.services.extract_prompt import build_extract_prompt
from backend.services.extract_service import (
    ExtractQualityError,
    JSONParseError,
    ParseResult,
    _MAX_REPAIR_ATTEMPTS,
    _extract_validation_errors,
    build_repair_prompt,
    parse_and_validate,
)
from backend.services.kimi_client import (
    KimiClient,
    get_model_name,
    is_retryable_error,
    retry_after_seconds,
)
from backend.services.paper_readiness import (
    papers_pending_summary,
    parsed_papers_in_project,
)

logger = logging.getLogger(__name__)

_EXTRACT_MAX_TOKENS = 4096

# ---------------------------------------------------------------------------
# SSE 广播基础设施
# ---------------------------------------------------------------------------

# job_id → set[asyncio.Queue]
_subscribers: dict[str, set[asyncio.Queue]] = {}
_subscribers_lock = asyncio.Lock()


def _sse_msg(data: dict) -> str:
    """构造 SSE 格式消息行."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _broadcast(job_id: str, event: dict) -> None:
    """向某个 job 的所有 SSE 订阅者广播事件."""
    async with _subscribers_lock:
        queues = _subscribers.get(job_id, set())
    for q in list(queues):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # 订阅者太慢，丢弃


async def subscribe_job_events(job_id: str) -> asyncio.Queue:
    """为 SSE 订阅者创建事件队列."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    async with _subscribers_lock:
        _subscribers.setdefault(job_id, set()).add(q)
    return q


async def unsubscribe_job_events(job_id: str, q: asyncio.Queue) -> None:
    """SSE 订阅者断开时移除队列."""
    async with _subscribers_lock:
        queues = _subscribers.get(job_id)
        if queues:
            queues.discard(q)
            if not queues:
                _subscribers.pop(job_id, None)


# ---------------------------------------------------------------------------
# 防重抽：查 claims 表判断哪些 paper 还需抽取
# ---------------------------------------------------------------------------


def get_papers_pending_for_job(job: ExtractJob, db: Session, force: bool = False) -> list[Paper]:
    """获取该 job 对应项目中待抽取的 paper 列表.

    "已抽过"的判断标准：claims 表中已存在该 paper_id 的记录（≥1条即算已抽）。
    不管 job.succeeded 计数器是多少 —— 以实际结果为准。

    Args:
        job: 当前 Job
        db: 数据库会话
        force: 如果为 True，跳过防重抽，返回所有 completed paper
    """
    # 1. 项目下已解析出可用全文的 paper（不要求已有摘要 / COMPLETED）
    project_papers = parsed_papers_in_project(db, job.project_id)

    if not project_papers:
        return []

    if force:
        return project_papers

    paper_ids = [p.id for p in project_papers]

    # 2. 查哪些 paper 已有 claims（一条足以判定"已抽过"）
    paper_ids_with_claims = set(
        row[0]
        for row in db.query(Claim.paper_id)
        .filter(Claim.paper_id.in_(paper_ids))
        .distinct()
        .all()
    )

    # 3. 待处理 = 有全文 且 无 claims
    return [p for p in project_papers if p.id not in paper_ids_with_claims]


def get_papers_pending_for_summary_job(
    job: ExtractJob, db: Session, force: bool = False,
) -> list[Paper]:
    """获取该 job 对应项目中待提取摘要的 paper 列表."""
    return papers_pending_summary(db, job.project_id, force=force)


def _get_full_text_from_db(paper_id: str) -> str:
    with SessionLocal() as db:
        pages = (
            db.query(PaperPage)
            .filter(PaperPage.paper_id == paper_id)
            .order_by(PaperPage.page_number)
            .all()
        )
    return "\n\n".join(p.text_content for p in pages if p.text_content)


def _save_extracted_data_db(db: Session, paper_id: str, parse_result: ParseResult) -> None:
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


def _rollback_paper_extracting(paper_id: str, message: str = "提取中断") -> None:
    """将卡在 extracting 的文献回退为 pending."""
    with SessionLocal() as db:
        p = db.query(Paper).filter(Paper.id == paper_id).first()
        if p and p.status == PaperStatus.EXTRACTING.value:
            p.status = PaperStatus.PENDING.value
            p.last_error = message[:500]
            db.commit()


async def process_one_summary_atomically(paper: Paper, job: ExtractJob) -> dict:
    """对一篇 paper 执行摘要提取并写库."""
    paper_id = paper.id
    display_title = paper.title or paper_id[:8]
    full_text = _get_full_text_from_db(paper_id)

    if not full_text.strip():
        _rollback_paper_extracting(paper_id, "全文为空，无法提取（可重提）")
        return {
            "status": "failed",
            "error": "全文为空",
            "title": display_title,
        }

    # 置 extracting
    with SessionLocal() as db_st:
        p = db_st.query(Paper).filter(Paper.id == paper_id).first()
        if p:
            p.status = PaperStatus.EXTRACTING.value
            p.extraction_attempts = (p.extraction_attempts or 0) + 1
            p.last_error = None
            db_st.commit()

    try:
        prompt = build_extract_prompt(full_text)
        client = KimiClient()
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
                if is_retryable_error(exc) and attempt < MAX_RETRIES:
                    delay = retry_after_seconds(exc, RETRY_BASE_DELAY * (2 ** attempt))
                    await asyncio.sleep(delay)
                else:
                    break

        if not extract_ok:
            err = str(last_error)[:500] if last_error else "未知错误"
            _rollback_paper_extracting(paper_id, f"调用失败（可重提）: {err}")
            return {"status": "failed", "error": err, "title": display_title}

        parse_result = None
        repair_errors: list[str] = []
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

        if parse_result is None:
            err = ("解析失败（可重提）: " + "; ".join(repair_errors[:5]))[:500]
            _rollback_paper_extracting(paper_id, err)
            return {"status": "failed", "error": err, "title": display_title}

        with SessionLocal() as db_res:
            p = db_res.query(Paper).filter(Paper.id == paper_id).first()
            if not p:
                return {"status": "failed", "error": "文献已不存在", "title": display_title}

            extracted = parse_result.data
            p.status = PaperStatus.COMPLETED.value
            p.extracted_at = datetime.utcnow()
            if parse_result.partial:
                p.last_error = "部分成功：缺失字段 " + ", ".join(parse_result.missing_fields)
            else:
                p.last_error = None
            _save_extracted_data_db(db_res, paper_id, parse_result)
            if extracted.get("title") and not p.title:
                p.title = extracted["title"]
            if extracted.get("authors") and not p.authors:
                p.authors = extracted["authors"]
            if extracted.get("year") and not p.year:
                p.year = extracted["year"]
            if extracted.get("journal") and not p.journal:
                p.journal = extracted["journal"]

            job_entry = (
                db_res.query(ExtractJob)
                .filter(ExtractJob.id == job.id)
                .with_for_update()
                .first()
            )
            if job_entry:
                job_entry.current_paper_id = None
                job_entry.succeeded = (job_entry.succeeded or 0) + 1
                job_entry.updated_at = datetime.utcnow()
            db_res.commit()

        return {
            "status": "success",
            "title": display_title,
            "partial": parse_result.partial,
        }
    except Exception as exc:
        logger.exception("[Job %s] 摘要提取异常 paper_id=%s", job.id, paper_id)
        _rollback_paper_extracting(paper_id, f"提取异常: {str(exc)[:200]}")
        return {"status": "failed", "error": str(exc)[:500], "title": display_title}
    finally:
        # 兜底：若仍以 extracting 收尾则回退
        _rollback_paper_extracting(paper_id, "任务中断，可重提")


# ---------------------------------------------------------------------------
# 单篇原子处理（claims）
# ---------------------------------------------------------------------------


async def process_one_paper_atomically(
    paper: Paper,
    job: ExtractJob,
    force: bool = False,
) -> dict:
    """对一篇 paper 执行 claims 抽取并原子写库.

    用 with db.begin() 整篇事务包裹：
    - force: 事务内先 DELETE 该 paper 旧 claims，再写入新 claims
    - 成功：全部 claims 写入 + job 进度更新 → COMMIT
    - 失败：全篇回滚 → 0 claims 写入，paper 标 failed

    Returns:
        {"status": "success"|"failed", "written": int, "error": str|None, "model_used": str}
    """
    t_start = time.perf_counter()
    title = paper.title or "未命名文献"
    model_name = get_model_name()

    # ── 读全文 ──
    with SessionLocal() as db_read:
        pages_raw = (
            db_read.query(PaperPage)
            .filter(PaperPage.paper_id == paper.id)
            .order_by(PaperPage.page_number)
            .all()
        )

    if not pages_raw:
        return {
            "status": "failed",
            "written": 0,
            "error": "全文为空，无法抽取",
            "model_used": model_name,
            "wall_time_seconds": 0,
        }

    full_text_parts: list[str] = []
    pages: list[PageBlock] = []
    for pp in pages_raw:
        text = pp.text_content or ""
        if text:
            full_text_parts.append(text)
        pages.append(PageBlock(page_number=pp.page_number, text=text))

    full_text = "\n\n".join(full_text_parts)
    if not full_text.strip():
        return {
            "status": "failed",
            "written": 0,
            "error": "全文为空，无法抽取",
            "model_used": model_name,
            "wall_time_seconds": 0,
        }

    logger.info(
        "[Job %s] 开始抽取 paper_id=%s title=%s chars=%d model=%s",
        job.id, paper.id, title, len(full_text), model_name,
    )

    # ── 调用 AI ──
    try:
        result = await extract_claims_for_paper(
            paper_id=paper.id,
            title=title,
            full_text=full_text,
            pages=pages,
        )
    except Exception as exc:
        logger.exception("[Job %s] 抽取异常 paper_id=%s", job.id, paper.id)
        return {
            "status": "failed",
            "written": 0,
            "error": str(exc)[:500],
            "model_used": model_name,
            "wall_time_seconds": round(time.perf_counter() - t_start, 2),
        }

    claims_list = result["claims"]
    rejected_list = result.get("rejected", [])
    wall_time = result["wall_time_seconds"]

    # Fix1 命门：切块失败（chunk_count==0 / no_chunks）= PDF 文本解析异常，判“失败”，
    # 绝不写 0 条还 succeeded += 1。注意：这里用 no_chunks（分块失败）而非 written==0
    # 作为失败信号——切块成功但确无可抽论断的“合法 0 条”不会进此分支（见下方事务）。
    if result.get("no_chunks"):
        logger.error(
            "[Job %s] paper_id=%s 切块失败(0 块/PDF 解析异常)，判失败不计入成功",
            job.id, paper.id,
        )
        return {
            "status": "failed",
            "written": 0,
            "error": "PDF 文本解析异常：未能切分章节（可能词间空格丢失），无法抽取 claims",
            "model_used": model_name,
            "wall_time_seconds": wall_time,
        }

    # ── 整篇事务写库 ──
    written = 0
    error_detail: Optional[str] = None

    with SessionLocal() as db:
        try:
            with db.begin():  # 显式事务边界（异常自动 ROLLBACK）
                # force 模式：先删除该 paper 的旧 claims
                if force:
                    old_count = (
                        db.query(Claim)
                        .filter(Claim.paper_id == paper.id)
                        .delete()
                    )
                    if old_count:
                        logger.info(
                            "[Job %s] force 重抽: paper_id=%s 删除旧 %d 条 claims",
                            job.id, paper.id, old_count,
                        )

                now = datetime.utcnow()
                for claim_dict in claims_list:
                    quote_text = claim_dict.get("quote", "")[:300]
                    quote_hash = hashlib.sha256(
                        normalize_text(quote_text).encode("utf-8")
                    ).hexdigest()
                    claim = Claim(
                        id=str(uuid.uuid4()),
                        paper_id=paper.id,
                        claim_form=claim_dict.get("claim_form", "state"),
                        subject=claim_dict.get("subject"),
                        topic=claim_dict.get("topic"),
                        direction=claim_dict.get("direction"),
                        comparison_result=claim_dict.get("comparison_result"),
                        magnitude=claim_dict.get("magnitude"),
                        context=claim_dict.get("context"),
                        stat_support=bool(claim_dict.get("stat_support", False)),
                        is_limitation=bool(claim_dict.get("is_limitation", False)),
                        quote=quote_text,
                        quote_hash=quote_hash,
                        quote_page=int(claim_dict.get("quote_page", 0)),
                        extraction_source="model",
                        quote_status=claim_dict.get("quote_status"),
                        char_span_start=claim_dict.get("char_span_start"),
                        char_span_end=claim_dict.get("char_span_end"),
                        notes=claim_dict.get("notes"),
                    )
                    db.add(claim)
                    written += 1

                # 更新 job 进度
                job_entry = (
                    db.query(ExtractJob)
                    .filter(ExtractJob.id == job.id)
                    .with_for_update()
                    .first()
                )
                if job_entry:
                    # 到这里 no_chunks 已被上面挡掉，故切块一定成功。即便 written==0
                    # （合法 0 条：确无可抽论断），也算该篇“成功处理”，不误判失败。
                    job_entry.current_paper_id = None
                    job_entry.succeeded += 1
                    job_entry.updated_at = now

                logger.info(
                    "[Job %s] paper_id=%s 写入 %d 条 claims (拒绝 %d 条), %.1fs",
                    job.id, paper.id, written, len(rejected_list), wall_time,
                )
        except Exception as exc:
            # db.begin() 的 __exit__ 已自动 ROLLBACK；此处捕获后返回失败结果，
            # 不再向上抛出，避免冒泡到 worker 外层导致 job 卡 RUNNING（孤儿）。
            logger.exception(
                "[Job %s] paper_id=%s 写库异常，事务回滚",
                job.id, paper.id,
            )
            error_detail = str(exc)[:500]

    if error_detail:
        return {
            "status": "failed",
            "written": 0,
            "error": error_detail,
            "model_used": model_name,
            "wall_time_seconds": wall_time,
        }

    # 拒绝日志
    for rj in rejected_list:
        logger.warning(
            "[Job %s] claim 被条件校验拒绝: paper_id=%s claim_form=%s subject=%s reasons=%s",
            job.id, paper.id,
            rj.get("claim_form"),
            rj.get("subject"),
            rj.get("_reject_reasons", []),
        )

    return {
        "status": "success",
        "written": written,
        "error": None,
        "model_used": model_name,
        "wall_time_seconds": wall_time,
        "rejected": len(rejected_list),
    }


# ---------------------------------------------------------------------------
# Job 进度更新辅助
# ---------------------------------------------------------------------------


def _update_job_status(job_id: str, **kwargs) -> None:
    """更新 job 行（非事务，独立提交）."""
    with SessionLocal() as db:
        job = db.query(ExtractJob).filter(ExtractJob.id == job_id).first()
        if job:
            for key, value in kwargs.items():
                setattr(job, key, value)
            job.updated_at = datetime.utcnow()
            db.commit()


def _refresh_job(job_id: str) -> Optional[ExtractJob]:
    """重新从 DB 读取 job 最新状态."""
    with SessionLocal() as db:
        return db.query(ExtractJob).filter(ExtractJob.id == job_id).first()


# ---------------------------------------------------------------------------
# Worker 主循环
# ---------------------------------------------------------------------------


_POLL_INTERVAL = 2.0  # 无任务时轮询间隔（秒）
_PAUSE_CHECK_INTERVAL = 1.0  # 暂停时检查恢复间隔（秒）
_PAPER_INTERVAL = 0.5  # 篇间间隔，防止 API 过载

# running 任务超过该时长无进展（updated_at 未刷新）视为孤儿，运行期自动判 interrupted
JOB_STALE_TIMEOUT_SECONDS = 600  # 10 分钟


def _reclaim_stale_running_jobs() -> int:
    """运行期自愈：把 updated_at 过旧的 running 任务判为 interrupted（孤儿回收）。

    不依赖重启；每轮轮询调用一次。返回回收数量。
    """
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(seconds=JOB_STALE_TIMEOUT_SECONDS)
    reclaimed = 0
    with SessionLocal() as db:
        stale = (
            db.query(ExtractJob)
            .filter(
                ExtractJob.status == JobStatus.RUNNING.value,
                ExtractJob.updated_at < cutoff,
            )
            .all()
        )
        for j in stale:
            j.status = JobStatus.INTERRUPTED.value
            reclaimed += 1
        if reclaimed:
            db.commit()
            logger.warning("运行期自愈：回收 %d 个超时 running 孤儿任务 → interrupted", reclaimed)
    return reclaimed


async def _run_summary_job(job: ExtractJob) -> None:
    """执行 summary_extract Job（逐篇摘要）."""
    with SessionLocal() as db:
        force = bool((job.error_summary or {}).get("force", False))
        pending_papers = get_papers_pending_for_summary_job(job, db, force=force)
        project = db.query(Project).filter(Project.id == job.project_id).first()
        project_name = project.name if project else "未知项目"
        model_name = get_model_name()

    if not pending_papers:
        logger.info("[Job %s] 无待摘要 paper，标记 completed", job.id)
        _update_job_status(job.id, status=JobStatus.COMPLETED.value)
        await _broadcast(job.id, {
            "type": "job_done",
            "job_id": job.id,
            "status": "completed",
            "total": job.total,
            "succeeded": job.succeeded,
            "failed": job.failed,
            "message": "所有文献摘要已提取完成",
        })
        return

    total_count = len(pending_papers)
    _update_job_status(
        job.id,
        status=JobStatus.RUNNING.value,
        total=total_count + (job.succeeded or 0),
        current=0,
        error_summary=job.error_summary or {},
    )

    await _broadcast(job.id, {
        "type": "job_status",
        "job_id": job.id,
        "status": "running",
        "project_id": job.project_id,
        "project_name": project_name,
        "total": total_count + (job.succeeded or 0),
        "succeeded": job.succeeded or 0,
        "failed": job.failed or 0,
        "pending": total_count,
        "model": model_name,
        "job_type": JobType.SUMMARY_EXTRACT.value,
    })

    for idx, paper in enumerate(pending_papers, start=1):
        current_job = _refresh_job(job.id)
        if current_job is None:
            break
        if current_job.status == JobStatus.CANCELLED.value:
            await _broadcast(job.id, {
                "type": "job_done",
                "job_id": job.id,
                "status": "cancelled",
                "message": "任务已取消",
            })
            break
        if current_job.status == JobStatus.PAUSED.value:
            while True:
                await asyncio.sleep(_PAUSE_CHECK_INTERVAL)
                refreshed = _refresh_job(job.id)
                if refreshed is None or refreshed.status != JobStatus.PAUSED.value:
                    break
            current_job = _refresh_job(job.id)
            if current_job is None or current_job.status == JobStatus.CANCELLED.value:
                break

        display_title = paper.title or paper.id[:8]
        _update_job_status(job.id, current=idx, current_paper_id=paper.id, updated_at=datetime.utcnow())

        await _broadcast(job.id, {
            "type": "paper_progress",
            "job_id": job.id,
            "current": idx,
            "total": total_count,
            "paper_id": paper.id,
            "title": display_title,
            "status": "extracting",
        })

        try:
            paper_result = await process_one_summary_atomically(paper, job)
        except Exception as exc:
            logger.exception("[Job %s] 摘要单篇未预期异常 paper_id=%s", job.id, paper.id)
            paper_result = {"status": "failed", "error": str(exc)[:500], "title": display_title}

        if paper_result["status"] == "success":
            refreshed = _refresh_job(job.id)
            await _broadcast(job.id, {
                "type": "paper_progress",
                "job_id": job.id,
                "current": idx,
                "total": total_count,
                "paper_id": paper.id,
                "title": display_title,
                "status": "completed",
                "partial": paper_result.get("partial", False),
                "succeeded": refreshed.succeeded if refreshed else idx,
                "failed": job.failed or 0,
            })
        else:
            with SessionLocal() as db:
                db_job = db.query(ExtractJob).filter(ExtractJob.id == job.id).first()
                if db_job:
                    db_job.failed = (db_job.failed or 0) + 1
                    db_job.updated_at = datetime.utcnow()
                    error_summary = db_job.error_summary or {}
                    error_summary[paper.id] = paper_result.get("error", "未知错误")
                    db_job.error_summary = error_summary
                    db.commit()
            await _broadcast(job.id, {
                "type": "paper_progress",
                "job_id": job.id,
                "current": idx,
                "total": total_count,
                "paper_id": paper.id,
                "title": display_title,
                "status": "failed",
                "error": paper_result.get("error", "未知错误")[:200],
            })

        await asyncio.sleep(_PAPER_INTERVAL)

    refreshed = _refresh_job(job.id)
    if refreshed and refreshed.status == JobStatus.RUNNING.value:
        _update_job_status(job.id, status=JobStatus.COMPLETED.value)

    await _broadcast(job.id, {
        "type": "job_done",
        "job_id": job.id,
        "status": "completed",
        "total": refreshed.total if refreshed else total_count,
        "succeeded": refreshed.succeeded if refreshed else total_count,
        "failed": refreshed.failed if refreshed else 0,
        "message": "摘要提取任务完成",
    })


async def extract_worker_loop() -> None:
    """后台 Job worker 主循环（claims + 摘要）."""
    logger.info("Extract worker 已启动，轮询间隔 %.1fs", _POLL_INTERVAL)

    while True:
        job = None
        try:
            _reclaim_stale_running_jobs()

            job = _dequeue_next_job()
            if job is None:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            logger.info(
                "[Worker] 拾取 job_id=%s type=%s project_id=%s status=%s",
                job.id, job.job_type, job.project_id, job.status,
            )

            if job.job_type == JobType.SUMMARY_EXTRACT.value:
                await _run_summary_job(job)
                continue

            # ── claims_extract 分支 ──
            with SessionLocal() as db:
                force = bool((job.error_summary or {}).get("force", False))
                pending_papers = get_papers_pending_for_job(job, db, force=force)
                project = db.query(Project).filter(Project.id == job.project_id).first()
                project_name = project.name if project else "未知项目"
                model_name = get_model_name()

            if not pending_papers:
                # 没有需要抽取的 paper，直接完成
                logger.info("[Job %s] 无待抽取 paper，标记 completed", job.id)
                _update_job_status(job.id, status=JobStatus.COMPLETED.value)
                await _broadcast(job.id, {
                    "type": "job_done",
                    "job_id": job.id,
                    "status": "completed",
                    "total": job.total,
                    "succeeded": job.succeeded,
                    "failed": job.failed,
                    "message": "所有文献已抽取完成",
                })
                continue

            # ── Step 3: 初始化 job 元数据 ──
            total_count = len(pending_papers)
            _update_job_status(
                job.id,
                status=JobStatus.RUNNING.value,
                total=total_count + (job.succeeded or 0),
                current=0,
                error_summary={},
            )

            await _broadcast(job.id, {
                "type": "job_status",
                "job_id": job.id,
                "status": "running",
                "project_id": job.project_id,
                "project_name": project_name,
                "total": total_count + (job.succeeded or 0),
                "succeeded": job.succeeded or 0,
                "failed": 0,
                "pending": total_count,
                "model": model_name,
            })

            # ── Step 4: 逐篇处理 ──
            for idx, paper in enumerate(pending_papers, start=1):
                # ──── PAPER BOUNDARY: 状态检查点 ────
                current_job = _refresh_job(job.id)
                if current_job is None:
                    logger.error("[Job %s] 记录消失，停止处理", job.id)
                    break

                if current_job.status == JobStatus.CANCELLED.value:
                    logger.info("[Job %s] 用户取消，停止", job.id)
                    await _broadcast(job.id, {
                        "type": "job_done",
                        "job_id": job.id,
                        "status": "cancelled",
                        "total": job.total,
                        "succeeded": job.succeeded or 0,
                        "failed": job.failed or 0,
                        "message": "任务已取消",
                    })
                    break

                if current_job.status == JobStatus.PAUSED.value:
                    logger.info("[Job %s] 用户暂停，等待恢复", job.id)
                    await _broadcast(job.id, {
                        "type": "job_status",
                        "job_id": job.id,
                        "status": "paused",
                        "message": "任务已暂停",
                    })

                    # 阻塞等待恢复
                    while True:
                        await asyncio.sleep(_PAUSE_CHECK_INTERVAL)
                        refreshed = _refresh_job(job.id)
                        if refreshed is None:
                            break
                        if refreshed.status == JobStatus.RUNNING.value:
                            logger.info("[Job %s] 恢复执行", job.id)
                            await _broadcast(job.id, {
                                "type": "job_status",
                                "job_id": job.id,
                                "status": "running",
                                "message": "任务已恢复",
                            })
                            break
                        if refreshed.status == JobStatus.CANCELLED.value:
                            logger.info("[Job %s] 暂停中被取消", job.id)
                            break

                    # 重新检查是否被取消
                    current_job = _refresh_job(job.id)
                    if current_job is None or current_job.status == JobStatus.CANCELLED.value:
                        await _broadcast(job.id, {
                            "type": "job_done",
                            "job_id": job.id,
                            "status": "cancelled" if current_job else "failed",
                            "message": "任务已取消",
                        })
                        break

                # ── 设置 current_paper_id ──
                display_title = paper.title or paper.id[:8]
                _update_job_status(job.id, current=idx, current_paper_id=paper.id)

                await _broadcast(job.id, {
                    "type": "paper_progress",
                    "job_id": job.id,
                    "current": idx,
                    "total": total_count,
                    "paper_id": paper.id,
                    "title": display_title,
                    "status": "extracting",
                    "succeeded": job.succeeded or 0,
                    "failed": job.failed or 0,
                })

                # ── 原子处理一篇（单篇异常不拖垮整个 job）──
                try:
                    paper_result = await process_one_paper_atomically(paper, job, force=force)
                except Exception as exc:
                    logger.exception("[Job %s] 单篇处理未预期异常 paper_id=%s", job.id, paper.id)
                    paper_result = {
                        "status": "failed",
                        "written": 0,
                        "error": str(exc)[:500],
                        "model_used": "",
                        "wall_time_seconds": 0,
                    }

                # ── 广播结果 ──
                if paper_result["status"] == "success":
                    # 刷新 job 以获取最新 succeeded 计数
                    refreshed = _refresh_job(job.id)
                    await _broadcast(job.id, {
                        "type": "paper_progress",
                        "job_id": job.id,
                        "current": idx,
                        "total": total_count,
                        "paper_id": paper.id,
                        "title": display_title,
                        "status": "completed",
                        "written": paper_result["written"],
                        "wall_time_seconds": paper_result["wall_time_seconds"],
                        "model": paper_result["model_used"],
                        "succeeded": (refreshed.succeeded if refreshed else (job.succeeded or 0) + idx),
                        "failed": job.failed or 0,
                    })
                else:
                    # 失败：更新 job.failed 计数器
                    with SessionLocal() as db:
                        db_job = db.query(ExtractJob).filter(ExtractJob.id == job.id).first()
                        if db_job:
                            db_job.failed = (db_job.failed or 0) + 1
                            db_job.updated_at = datetime.utcnow()
                            # 记录错误摘要
                            error_summary = db_job.error_summary or {}
                            error_summary[paper.id] = paper_result.get("error", "未知错误")
                            db_job.error_summary = error_summary
                            db.commit()

                    await _broadcast(job.id, {
                        "type": "paper_progress",
                        "job_id": job.id,
                        "current": idx,
                        "total": total_count,
                        "paper_id": paper.id,
                        "title": display_title,
                        "status": "failed",
                        "error": paper_result.get("error", "未知错误")[:200],
                        "succeeded": job.succeeded or 0,
                        "failed": (job.failed or 0) + 1,
                    })

                # 篇间间隔
                await asyncio.sleep(_PAPER_INTERVAL)

            # ── Step 5: 完成 ──
            refreshed = _refresh_job(job.id)
            if refreshed and refreshed.status == JobStatus.RUNNING.value:
                _update_job_status(job.id, status=JobStatus.COMPLETED.value)

            await _broadcast(job.id, {
                "type": "job_done",
                "job_id": job.id,
                "status": "completed",
                "total": refreshed.total if refreshed else total_count,
                "succeeded": refreshed.succeeded if refreshed else total_count,
                "failed": refreshed.failed if refreshed else 0,
                "message": "Claims 抽取任务完成",
            })

            logger.info(
                "[Job %s] 完成: succeeded=%d failed=%d",
                job.id,
                refreshed.succeeded if refreshed else total_count,
                refreshed.failed if refreshed else 0,
            )

        except asyncio.CancelledError:
            logger.info("Extract worker 收到关闭信号，退出")
            # 收尾：正在跑的 job 置 interrupted，避免留 running 孤儿
            try:
                if job is not None:
                    cur = _refresh_job(job.id)
                    if cur and cur.status == JobStatus.RUNNING.value:
                        _update_job_status(job.id, status=JobStatus.INTERRUPTED.value)
                        logger.info("[Job %s] 关闭时置 interrupted", job.id)
            except Exception:
                logger.exception("关闭收尾重置 job 失败")
            break
        except Exception:
            logger.exception("Extract worker 未预期异常，自愈收尾后继续")
            # 自愈：把当前在跑的 job 置 failed 收尾，绝不留 running 孤儿
            try:
                if job is not None:
                    cur = _refresh_job(job.id)
                    if cur and cur.status == JobStatus.RUNNING.value:
                        _update_job_status(job.id, status=JobStatus.FAILED.value)
                        await _broadcast(job.id, {
                            "type": "job_done",
                            "job_id": job.id,
                            "status": "failed",
                            "message": "任务异常已自动收尾，可重新发起",
                        })
                        logger.info("[Job %s] 异常自愈置 failed", job.id)
            except Exception:
                logger.exception("自愈重置 job 失败")
            await asyncio.sleep(_POLL_INTERVAL)

    logger.info("Extract worker 已停止")


# 兼容旧名
claims_worker_loop = extract_worker_loop


def _dequeue_next_job() -> Optional[ExtractJob]:
    """从 DB 取出下一个可运行的 Job（claims 或 summary）."""
    with SessionLocal() as db:
        job = (
            db.query(ExtractJob)
            .filter(
                ExtractJob.job_type.in_([
                    JobType.CLAIMS_EXTRACT.value,
                    JobType.SUMMARY_EXTRACT.value,
                ]),
                ExtractJob.status == JobStatus.QUEUED.value,
            )
            .order_by(ExtractJob.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if not job:
            return None

        # 抢占
        job.status = JobStatus.RUNNING.value
        db.commit()
        # expire_on_commit=False，job 仍是有效对象
        return job


__all__ = [
    "extract_worker_loop",
    "claims_worker_loop",
    "subscribe_job_events",
    "unsubscribe_job_events",
    "get_papers_pending_for_job",
    "get_papers_pending_for_summary_job",
    "JOB_STALE_TIMEOUT_SECONDS",
]
