"""Claims 抽取 Job Worker.

后台 asyncio 任务：
- 轮询 queued/interrupted 的 claims_extract Job
- 按 paper 边界逐篇抽取，每篇用 with db.begin() 整篇事务写库
- cancel/pause 在 paper 边界检查 job.status
- resume 防重抽：直查 claims 表，已有 claims 的 paper 跳过
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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.tables import (
    Claim,
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
from backend.services.kimi_client import get_model_name

logger = logging.getLogger(__name__)

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
    # 1. 项目下所有已完成全文解析的 paper
    project_papers = (
        db.query(Paper)
        .filter(
            Paper.project_id == job.project_id,
            Paper.status == PaperStatus.COMPLETED.value,
        )
        .all()
    )

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


# ---------------------------------------------------------------------------
# 单篇原子处理
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

    # ── 整篇事务写库 ──
    written = 0
    error_detail: Optional[str] = None

    with SessionLocal() as db:
        with db.begin():  # 显式事务边界
            try:
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
                    job_entry.current_paper_id = None
                    job_entry.succeeded += 1
                    job_entry.updated_at = now

                logger.info(
                    "[Job %s] paper_id=%s 写入 %d 条 claims (拒绝 %d 条), %.1fs",
                    job.id, paper.id, written, len(rejected_list), wall_time,
                )
            except Exception as exc:
                # db.begin() 的 __exit__ 会自动 ROLLBACK
                logger.exception(
                    "[Job %s] paper_id=%s 写库异常，事务回滚",
                    job.id, paper.id,
                )
                error_detail = str(exc)[:500]
                raise  # 重新抛出，让 with db.begin() 触发回滚

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


async def claims_worker_loop() -> None:
    """Claims 抽取 worker 主循环.

    生命周期：由 lifespan 在启动时 asyncio.create_task，关闭时 cancel。
    """
    logger.info("Claims worker 已启动，轮询间隔 %.1fs", _POLL_INTERVAL)

    while True:
        try:
            # ── Step 1: 取下一个可运行的 job ──
            job = _dequeue_next_job()
            if job is None:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            logger.info(
                "[Worker] 拾取 job_id=%s project_id=%s status=%s",
                job.id, job.project_id, job.status,
            )

            # ── Step 2: 获取待抽取 paper 列表（防重抽）──
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

                # ── 原子处理一篇 ──
                paper_result = await process_one_paper_atomically(paper, job, force=force)

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
            logger.info("Claims worker 收到关闭信号，退出")
            break
        except Exception:
            logger.exception("Claims worker 未预期异常，继续运行")

    logger.info("Claims worker 已停止")


def _dequeue_next_job() -> Optional[ExtractJob]:
    """从 DB 取出下一个可运行的 claims_extract Job.

    仅拾取 queued 状态的 Job。
    interrupted 状态必须由用户手动 POST resume → queued 后才会被拾取。
    取出后立即置为 running（抢占）。
    """
    with SessionLocal() as db:
        job = (
            db.query(ExtractJob)
            .filter(
                ExtractJob.job_type == JobType.CLAIMS_EXTRACT.value,
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
    "claims_worker_loop",
    "subscribe_job_events",
    "unsubscribe_job_events",
    "get_papers_pending_for_job",
]
