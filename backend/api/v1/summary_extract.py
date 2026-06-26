"""摘要批量提取 API（Job 化，与 claims 同架构）.

路由:
- POST /api/v1/projects/{project_id}/summary-extract/start
- GET  /api/v1/projects/{project_id}/summary-extract/subscribe
- GET  /api/v1/projects/{project_id}/summary-extract/pending-count
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_

from backend.models.tables import ExtractJob, JobStatus, JobType, Project
from backend.services.db import SessionLocal
from backend.services.extract_job_worker import (
    JOB_STALE_TIMEOUT_SECONDS,
    subscribe_job_events,
    unsubscribe_job_events,
)
from backend.services.kimi_client import get_model_name
from backend.services.paper_readiness import (
    parsed_papers_in_project,
    papers_pending_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["summary-extract"])


def _get_model_name_safe() -> str:
    try:
        return get_model_name()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SummaryExtractStartRequest(BaseModel):
    force: bool = Field(False, description="强制重提：对已提取摘要的文献重新提取")


class PendingSummaryCountResponse(BaseModel):
    pending_count: int


class SummaryExtractStartResponse(BaseModel):
    job_id: str
    project_id: str
    status: str
    pending_paper_count: int
    model: str


def _pending_summary_paper_ids(db, project_id: str, *, force: bool = False) -> list[str]:
    return [p.id for p in papers_pending_summary(db, project_id, force=force)]


def _all_parsed_paper_ids(db, project_id: str) -> list[str]:
    return [p.id for p in parsed_papers_in_project(db, project_id)]


@router.get(
    "/{project_id}/summary-extract/pending-count",
    response_model=PendingSummaryCountResponse,
)
def get_pending_summary_count(project_id: str) -> PendingSummaryCountResponse:
    with SessionLocal() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
        pending = _pending_summary_paper_ids(db, project_id, force=False)
        return PendingSummaryCountResponse(pending_count=len(pending))


@router.post(
    "/{project_id}/summary-extract/start",
    response_model=SummaryExtractStartResponse,
    status_code=201,
)
def start_summary_extract(
    project_id: str,
    body: SummaryExtractStartRequest,
) -> SummaryExtractStartResponse:
    model_name = _get_model_name_safe()

    with SessionLocal() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")

        if body.force:
            pending_ids = _pending_summary_paper_ids(db, project_id, force=True)
        else:
            pending_ids = _pending_summary_paper_ids(db, project_id, force=False)

        if not _all_parsed_paper_ids(db, project_id):
            raise HTTPException(
                status_code=400,
                detail="项目下无可提取摘要的文献（需先上传并成功解析 PDF）",
            )
        if not pending_ids:
            raise HTTPException(
                status_code=400,
                detail="无待提摘要文献：该项目文献均已提取摘要，或尚无已解析全文的文献",
            )

        stale_cutoff = datetime.utcnow() - timedelta(seconds=JOB_STALE_TIMEOUT_SECONDS)
        existing = (
            db.query(ExtractJob)
            .filter(
                ExtractJob.project_id == project_id,
                ExtractJob.job_type == JobType.SUMMARY_EXTRACT.value,
                or_(
                    ExtractJob.status.in_([
                        JobStatus.QUEUED.value,
                        JobStatus.PAUSED.value,
                    ]),
                    and_(
                        ExtractJob.status == JobStatus.RUNNING.value,
                        ExtractJob.updated_at >= stale_cutoff,
                    ),
                ),
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"该项目已有进行中的摘要提取任务 (job_id={existing.id}, status={existing.status})",
            )

        job = ExtractJob(
            id=str(uuid.uuid4()),
            project_id=project_id,
            job_type=JobType.SUMMARY_EXTRACT.value,
            status=JobStatus.QUEUED.value,
            total=len(pending_ids),
            current=0,
            succeeded=0,
            failed=0,
            error_summary={"force": True} if body.force else None,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        logger.info(
            "创建 summary_extract job_id=%s project_id=%s pending=%d",
            job.id, project_id, len(pending_ids),
        )

    return SummaryExtractStartResponse(
        job_id=job.id,
        project_id=project_id,
        status=job.status,
        pending_paper_count=len(pending_ids),
        model=model_name,
    )


@router.get("/{project_id}/summary-extract/subscribe")
async def subscribe_summary_extract(
    project_id: str,
    job_id: str = Query(..., description="Job ID"),
    request: Request = None,  # noqa: ARG001
) -> StreamingResponse:
    with SessionLocal() as db:
        job = db.query(ExtractJob).filter(ExtractJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} 不存在")
        if job.project_id != project_id:
            raise HTTPException(status_code=400, detail=f"Job 不属于项目 {project_id}")
        if job.job_type != JobType.SUMMARY_EXTRACT.value:
            raise HTTPException(status_code=400, detail="Job 类型不是 summary_extract")

    q = await subscribe_job_events(job_id)

    _TERMINAL_STATUSES = {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
        JobStatus.INTERRUPTED.value,
    }

    async def event_generator() -> AsyncIterator[str]:
        try:
            with SessionLocal() as db:
                job = db.query(ExtractJob).filter(ExtractJob.id == job_id).first()
                if job:
                    yield f"data: {json.dumps({'type': 'job_status', 'job_id': job.id, 'status': job.status, 'total': job.total, 'succeeded': job.succeeded, 'failed': job.failed, 'current': job.current}, ensure_ascii=False)}\n\n"
                    if job.status in _TERMINAL_STATUSES:
                        yield f"data: {json.dumps({'type': 'job_done', 'job_id': job.id, 'status': job.status, 'total': job.total or 0, 'succeeded': job.succeeded or 0, 'failed': job.failed or 0, 'message': '任务已结束'}, ensure_ascii=False)}\n\n"
                        return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "job_done":
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await unsubscribe_job_events(job_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
