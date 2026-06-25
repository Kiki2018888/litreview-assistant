"""Claims 抽取 API.

路由:
- POST /api/v1/projects/{project_id}/claims-extract        — 同步单篇抽取（保留，已加事务保护）
- POST /api/v1/projects/{project_id}/claims-extract/start  — 创建 Job 后台抽取
- GET  /api/v1/projects/{project_id}/claims-extract/subscribe — SSE 订阅 Job 进度
- POST /api/v1/jobs/{job_id}/resume  — 恢复 interrupted Job
- POST /api/v1/jobs/{job_id}/pause   — 暂停 running Job
- POST /api/v1/jobs/{job_id}/cancel  — 取消 Job
- GET  /api/v1/jobs/{job_id}/status  — 查看 Job 状态/进度
- GET  /api/v1/projects/{project_id}/claims — 查看项目下 claims 列表
- GET  /api/v1/claims/estimate       — 模型耗时预估
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.models.tables import Claim, ExtractJob, JobStatus, JobType, Paper, PaperPage, PaperStatus, Project
from backend.services.claim_extract_prompt import normalize_text
from backend.services.claim_extractor import (
    PageBlock,
    estimate_extraction_time,
    extract_claims_for_paper,
)
from backend.services.db import SessionLocal, get_db
from backend.services.extract_job_worker import (
    JOB_STALE_TIMEOUT_SECONDS,
    subscribe_job_events,
    unsubscribe_job_events,
)
from backend.services.kimi_client import get_model_name

logger = logging.getLogger(__name__)


def _get_model_name_safe() -> str:
    """安全获取模型名称，Key 未配置时返回友好 400 错误而非 500."""
    try:
        return get_model_name()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

router = APIRouter(prefix="/api/v1/projects", tags=["claims"])

# 另建独立前缀供 estimate 端点和 jobs 端点
estimate_router = APIRouter(prefix="/api/v1/claims", tags=["claims"])
jobs_router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class ClaimsExtractRequest(BaseModel):
    paper_id: str = Field(..., description="待抽取的文献 ID")
    model: Optional[str] = Field(None, description="可选指定模型，不传则用系统配置")
    force: bool = Field(False, description="强制重抽：先删旧 claims 再抽取（覆盖模式）")


class ClaimItem(BaseModel):
    """单条 claim 摘要（列表返回）."""
    id: str
    claim_form: str
    subject: Optional[str] = None
    topic: Optional[str] = None
    direction: Optional[str] = None
    comparison_result: Optional[str] = None
    magnitude: Optional[str] = None
    stat_support: bool = False
    is_limitation: bool = False
    quote: str
    quote_page: int
    quote_status: Optional[str] = None
    notes: Optional[str] = None


class ClaimsExtractResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    paper_id: str
    title: str
    total_extracted: int       # AI 抽出（去重后）总数
    written: int               # 通过校验写库数
    rejected: int              # 校验拒绝数
    chunk_count: int           # 分块数
    wall_time_seconds: float   # 总耗时
    model_used: str
    estimate: dict             # 预估信息
    rejected_samples: list[dict] = []  # 被拒记录 sample（最多 5 条）


class ClaimsListResponse(BaseModel):
    project_id: str
    paper_id: Optional[str] = None
    total: int
    claims: list[ClaimItem]


class EstimateResponse(BaseModel):
    paper_count: int
    estimate: dict


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/claims-extract
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/claims-extract",
    response_model=ClaimsExtractResponse,
    summary="单篇文献 claims 抽取（同步）",
)
async def extract_claims(
    project_id: str,
    body: ClaimsExtractRequest,
    db: Session = Depends(get_db),
):
    """对项目下指定文献执行 claims 抽取（同步，本步不做 Job 化）.

    流程：
    1. 校验文献存在且属于该项目
    2. force=false 且已有 claims → 报提示"已抽取过，如需重抽请用 force"
    3. force=true → 事务内先删旧 claims 再写新 claims
    4. 从 paper_pages 读全文
    5. 分块 → 并发 AI → 去重 → quote_locator → 条件校验
    6. 通过校验的写入 claims 表（含 quote_hash），被拒的记录记日志并返回 sample
    7. 返回抽取摘要
    """
    # ── 1. 校验文献 ──
    paper = db.query(Paper).filter(
        Paper.id == body.paper_id,
        Paper.project_id == project_id,
    ).first()
    if not paper:
        raise HTTPException(
            status_code=404,
            detail=f"文献 {body.paper_id} 不存在或不属于项目 {project_id}",
        )

    title = paper.title or "未命名文献"

    # ── 1.5 force 检查：已有 claims 时的行为 ──
    existing_count = db.query(Claim).filter(Claim.paper_id == body.paper_id).count()
    if existing_count > 0:
        if not body.force:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"该文献已抽取过 {existing_count} 条 claims。"
                    f"如需强制重抽（先删旧数据再抽取），请设置 force=true"
                ),
            )
        else:
            logger.info(
                "force 重抽: paper_id=%s, 将先删除旧 %d 条 claims",
                body.paper_id, existing_count,
            )

    # ── 2. 读取全文 ──
    pages_raw = (
        db.query(PaperPage)
        .filter(PaperPage.paper_id == body.paper_id)
        .order_by(PaperPage.page_number)
        .all()
    )
    if not pages_raw:
        raise HTTPException(status_code=400, detail="文献全文为空，无法抽取")

    full_text_parts: list[str] = []
    pages: list[PageBlock] = []
    for pp in pages_raw:
        text = pp.text_content or ""
        if text:
            full_text_parts.append(text)
        pages.append(PageBlock(page_number=pp.page_number, text=text))

    full_text = "\n\n".join(full_text_parts)
    if not full_text.strip():
        raise HTTPException(status_code=400, detail="文献全文为空，无法抽取")

    # ── 3. 预估信息 ──
    model_name = body.model or _get_model_name_safe()
    estimate = estimate_extraction_time(model_name, paper_count=1)

    logger.info(
        "开始 claims 抽取: paper_id=%s title=%s chars=%d model=%s",
        body.paper_id, title, len(full_text), model_name,
    )

    # ── 4. 执行抽取 ──
    try:
        result = await extract_claims_for_paper(
            paper_id=body.paper_id,
            title=title,
            full_text=full_text,
            pages=pages,
        )
    except Exception as exc:
        logger.exception("claims 抽取失败: paper_id=%s", body.paper_id)
        raise HTTPException(
            status_code=500,
            detail=f"抽取失败: {str(exc)[:300]}",
        )

    claims_list = result["claims"]
    rejected_list = result["rejected"]

    # ── 5. 写入 claims 表（事务保护：全写或全不写）──
    written = 0
    try:
        with db.begin_nested() as savepoint:
            # force 重抽：先删除该 paper 的旧 claims
            if body.force and existing_count > 0:
                db.query(Claim).filter(Claim.paper_id == body.paper_id).delete()
                logger.info("force 重抽: 已删除 paper_id=%s 的 %d 条旧 claims", body.paper_id, existing_count)

            for claim_dict in claims_list:
                quote_text = claim_dict.get("quote", "")[:300]
                quote_hash = hashlib.sha256(
                    normalize_text(quote_text).encode("utf-8")
                ).hexdigest()
                claim = Claim(
                    id=str(uuid.uuid4()),
                    paper_id=body.paper_id,
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
            # savepoint 退出时：全部成功 → 提升到外层 commit；任一失败 → 回滚
    except Exception as exc:
        logger.exception("写入 claims 事务失败，全篇回滚: paper_id=%s", body.paper_id)
        raise HTTPException(
            status_code=500,
            detail=f"claims 写库失败（事务回滚，0条写入）: {str(exc)[:200]}",
        )

    db.commit()

    # ── 6. 记录拒绝日志 ──
    for rj in rejected_list:
        logger.warning(
            "claim 被条件校验拒绝: claim_form=%s subject=%s reasons=%s quote=%s",
            rj.get("claim_form"),
            rj.get("subject"),
            rj.get("_reject_reasons", []),
            rj.get("quote", "")[:100],
        )

    return ClaimsExtractResponse(
        paper_id=body.paper_id,
        title=title,
        total_extracted=len(claims_list) + len(rejected_list),
        written=written,
        rejected=len(rejected_list),
        chunk_count=len(result["chunk_stats"]),
        wall_time_seconds=result["wall_time_seconds"],
        model_used=model_name,
        estimate=estimate,
        rejected_samples=rejected_list[:5],
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/claims
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/claims",
    response_model=ClaimsListResponse,
    summary="查看项目下 claims 列表",
)
async def list_claims(
    project_id: str,
    paper_id: Optional[str] = Query(None, description="按文献筛选"),
    limit: int = Query(100, ge=1, le=500, description="返回条数上限"),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """查看项目下已抽取的 claims 列表（供验证）."""
    # 校验项目存在
    from backend.models.tables import Project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")

    # 子查询：该项目下的 paper IDs
    paper_ids_subq = db.query(Paper.id).filter(Paper.project_id == project_id)
    if paper_id:
        paper_ids_subq = paper_ids_subq.filter(Paper.id == paper_id)

    paper_ids = [row[0] for row in paper_ids_subq.all()]
    if not paper_ids:
        return ClaimsListResponse(
            project_id=project_id, paper_id=paper_id, total=0, claims=[],
        )

    total = (
        db.query(Claim)
        .filter(Claim.paper_id.in_(paper_ids))
        .count()
    )

    rows = (
        db.query(Claim)
        .filter(Claim.paper_id.in_(paper_ids))
        .order_by(Claim.quote_page, Claim.id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    claims = [
        ClaimItem(
            id=row.id,
            claim_form=row.claim_form,
            subject=row.subject,
            topic=row.topic,
            direction=row.direction,
            comparison_result=row.comparison_result,
            magnitude=row.magnitude,
            stat_support=row.stat_support,
            is_limitation=row.is_limitation,
            quote=row.quote,
            quote_page=row.quote_page,
            quote_status=row.quote_status,
            notes=row.notes,
        )
        for row in rows
    ]

    return ClaimsListResponse(
        project_id=project_id,
        paper_id=paper_id,
        total=total,
        claims=claims,
    )


# ---------------------------------------------------------------------------
# GET /claims/by-paper/{paper_id} — 单篇文献 claims（文献库详情用，项目无关）
# ---------------------------------------------------------------------------


@estimate_router.get(
    "/by-paper/{paper_id}",
    response_model=ClaimsListResponse,
    summary="查看单篇文献已抽取的 claims",
)
def list_claims_by_paper(paper_id: str, db: Session = Depends(get_db)):
    """供文献库详情面板查看某篇文献的 claims（无需 project_id）."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail=f"文献 {paper_id} 不存在")

    rows = (
        db.query(Claim)
        .filter(Claim.paper_id == paper_id)
        .order_by(Claim.quote_page, Claim.id)
        .all()
    )
    claims = [
        ClaimItem(
            id=row.id,
            claim_form=row.claim_form,
            subject=row.subject,
            topic=row.topic,
            direction=row.direction,
            comparison_result=row.comparison_result,
            magnitude=row.magnitude,
            stat_support=row.stat_support,
            is_limitation=row.is_limitation,
            quote=row.quote,
            quote_page=row.quote_page,
            quote_status=row.quote_status,
            notes=row.notes,
        )
        for row in rows
    ]
    return ClaimsListResponse(
        project_id=paper.project_id or "",
        paper_id=paper_id,
        total=len(claims),
        claims=claims,
    )


# ---------------------------------------------------------------------------
# GET /claims/estimate — 模型耗时预估
# ---------------------------------------------------------------------------


@estimate_router.get(
    "/estimate",
    response_model=EstimateResponse,
    summary="模型耗时预估",
)
async def estimate_cost(
    paper_count: int = Query(1, ge=1, le=500, description="待抽取文献数"),
    model: Optional[str] = Query(None, description="模型名，不传则用系统配置"),
):
    """根据当前配置模型 + 文献数，返回预估耗时."""
    model_name = model or _get_model_name_safe()
    est = estimate_extraction_time(model_name, paper_count=paper_count)
    return EstimateResponse(paper_count=paper_count, estimate=est)


# ---------------------------------------------------------------------------
# Job 相关请求/响应模型
# ---------------------------------------------------------------------------


class ClaimsExtractStartRequest(BaseModel):
    """创建 claims 抽取 Job 请求."""
    model: Optional[str] = Field(None, description="可选指定模型，不传则用系统配置")
    force: bool = Field(False, description="强制重抽：跳过防重抽，对已抽 paper 先删旧 claims 再抽")


def _pending_claims_paper_ids(db: Session, project_id: str, *, force: bool = False) -> list[str]:
    """返回项目下待抽取 claims 的文献 ID 列表."""
    completed_paper_ids = [
        row[0]
        for row in db.query(Paper.id)
        .filter(
            Paper.project_id == project_id,
            Paper.status == PaperStatus.COMPLETED.value,
        )
        .all()
    ]
    if not completed_paper_ids:
        return []
    if force:
        return completed_paper_ids
    papers_with_claims = {
        row[0]
        for row in db.query(Claim.paper_id)
        .filter(Claim.paper_id.in_(completed_paper_ids))
        .distinct()
        .all()
    }
    return [pid for pid in completed_paper_ids if pid not in papers_with_claims]


class PendingClaimsCountResponse(BaseModel):
    pending_count: int


@router.get(
    "/{project_id}/claims-extract/pending-count",
    response_model=PendingClaimsCountResponse,
    summary="待抽取 claims 的文献数量",
)
def get_pending_claims_count(project_id: str) -> PendingClaimsCountResponse:
    """统计项目下已完成解析且尚未抽取 claims 的文献数."""
    with SessionLocal() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")
        pending = _pending_claims_paper_ids(db, project_id, force=False)
        return PendingClaimsCountResponse(pending_count=len(pending))


class ClaimsExtractStartResponse(BaseModel):
    job_id: str
    project_id: str
    status: str
    pending_paper_count: int
    model: str
    estimate: dict


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    project_id: str
    total: int
    current: int
    succeeded: int
    failed: int
    current_paper_id: Optional[str] = None
    current_paper_title: Optional[str] = None
    error_summary: Optional[dict] = None
    created_at: str
    updated_at: str


class JobActionResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str
    message: str = ""


# ---------------------------------------------------------------------------
# POST /{project_id}/claims-extract/start — 创建 Job
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/claims-extract/start",
    response_model=ClaimsExtractStartResponse,
    status_code=201,
    summary="创建 claims 抽取后台任务",
)
def start_claims_extract(
    project_id: str,
    body: ClaimsExtractStartRequest,
) -> ClaimsExtractStartResponse:
    """对项目下所有已完成全文解析的文献创建 claims_extract Job.

    已抽取过 claims 的文献会被防重抽机制自动跳过。
    设置 force=true 可跳过防重抽，对已抽 paper 先删旧 claims 再重新抽取。
    """
    model_name = body.model or _get_model_name_safe()

    with SessionLocal() as db:
        # 校验项目
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")

        # 统计 pending paper 数（completed 且暂无 claims 的）
        if body.force:
            pending_paper_ids = _pending_claims_paper_ids(db, project_id, force=True)
            if pending_paper_ids:
                logger.info(
                    "force 重抽 job: project_id=%s, 包含全部 %d 篇文献（含已抽过的）",
                    project_id, len(pending_paper_ids),
                )
        else:
            pending_paper_ids = _pending_claims_paper_ids(db, project_id, force=False)

        if not _pending_claims_paper_ids(db, project_id, force=True):
            raise HTTPException(status_code=400, detail="项目下无已完成全文解析的文献")

        if not pending_paper_ids:
            raise HTTPException(
                status_code=400,
                detail="无待抽文献：请先完成摘要解析，或该项目文献已全部抽取过",
            )

        # 检查是否有真正进行中的同类型 job：
        # queued/paused 一律拦截；running 仅在"未超时（updated_at 较新）"时才拦截，
        # 超时的 running 视为孤儿（由 worker 自愈回收），不再永久挡住后续发起。
        stale_cutoff = datetime.utcnow() - timedelta(seconds=JOB_STALE_TIMEOUT_SECONDS)
        existing = (
            db.query(ExtractJob)
            .filter(
                ExtractJob.project_id == project_id,
                ExtractJob.job_type == JobType.CLAIMS_EXTRACT.value,
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
                detail=f"该项目已有进行中的 claims 抽取任务 (job_id={existing.id}, status={existing.status})",
            )

        # 创建 Job
        job = ExtractJob(
            id=str(uuid.uuid4()),
            project_id=project_id,
            job_type=JobType.CLAIMS_EXTRACT.value,
            status=JobStatus.QUEUED.value,
            total=len(pending_paper_ids),
            current=0,
            succeeded=0,
            failed=0,
            error_summary={"force": True} if body.force else None,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        estimate = estimate_extraction_time(model_name, paper_count=len(pending_paper_ids))

        logger.info(
            "创建 claims_extract job_id=%s project_id=%s pending=%d model=%s",
            job.id, project_id, len(pending_paper_ids), model_name,
        )

    return ClaimsExtractStartResponse(
        job_id=job.id,
        project_id=project_id,
        status=job.status,
        pending_paper_count=len(pending_paper_ids),
        model=model_name,
        estimate=estimate,
    )


# ---------------------------------------------------------------------------
# GET /{project_id}/claims-extract/subscribe — SSE 进度订阅
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/claims-extract/subscribe",
    summary="SSE 订阅 claims 抽取进度",
)
async def subscribe_claims_extract(
    project_id: str,
    job_id: str = Query(..., description="Job ID"),
    request: Request = None,  # noqa: ARG001
) -> StreamingResponse:
    """SSE 端点：订阅某个 claims_extract Job 的实时进度事件.

    事件类型:
    - job_status: job 状态变更
    - paper_progress: 单篇进度
    - error: 错误
    - job_done: 任务完成
    """
    # 校验 job 存在
    with SessionLocal() as db:
        job = db.query(ExtractJob).filter(ExtractJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} 不存在")
        if job.project_id != project_id:
            raise HTTPException(status_code=400, detail=f"Job 不属于项目 {project_id}")

    q = await subscribe_job_events(job_id)

    async def event_generator() -> AsyncIterator[str]:
        try:
            # 先发送当前状态
            with SessionLocal() as db:
                job = db.query(ExtractJob).filter(ExtractJob.id == job_id).first()
                if job:
                    yield f"data: {json.dumps({'type': 'job_status', 'job_id': job.id, 'status': job.status, 'total': job.total, 'succeeded': job.succeeded, 'failed': job.failed, 'current': job.current}, ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "job_done":
                        break
                except asyncio.TimeoutError:
                    # 心跳防止连接断开
                    yield f": heartbeat\n\n"
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


# ---------------------------------------------------------------------------
# Job 控制端点 (jobs_router, prefix=/api/v1/jobs)
# ---------------------------------------------------------------------------


def _get_job_or_404(db: Session, job_id: str) -> ExtractJob:
    job = db.query(ExtractJob).filter(ExtractJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} 不存在")
    return job


@jobs_router.get(
    "/{job_id}/status",
    response_model=JobStatusResponse,
    summary="查看 Job 状态与进度",
)
def get_job_status(job_id: str) -> JobStatusResponse:
    """查看 job 的当前状态、进度计数、错误摘要."""
    with SessionLocal() as db:
        job = _get_job_or_404(db, job_id)

        current_paper_title = None
        if job.current_paper_id:
            paper = db.query(Paper).filter(Paper.id == job.current_paper_id).first()
            if paper:
                current_paper_title = paper.title

    return JobStatusResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        project_id=job.project_id,
        total=job.total or 0,
        current=job.current or 0,
        succeeded=job.succeeded or 0,
        failed=job.failed or 0,
        current_paper_id=job.current_paper_id,
        current_paper_title=current_paper_title,
        error_summary=job.error_summary,
        created_at=job.created_at.isoformat() if job.created_at else "",
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
    )


@jobs_router.post(
    "/{job_id}/resume",
    response_model=JobActionResponse,
    summary="恢复 interrupted 或 paused Job",
)
def resume_job(job_id: str) -> JobActionResponse:
    """恢复 interrupted/paused 的 Job.

    - interrupted → queued（重新排队，worker 按 claims 表防重抽）
    - paused → running（继续执行）
    """
    with SessionLocal() as db:
        job = _get_job_or_404(db, job_id)

        if job.status == JobStatus.INTERRUPTED.value:
            job.status = JobStatus.QUEUED.value
            msg = "Job 已恢复排队，worker 将按防重抽逻辑仅处理未抽取的文献"
        elif job.status == JobStatus.PAUSED.value:
            job.status = JobStatus.RUNNING.value
            msg = "Job 已恢复执行"
        else:
            raise HTTPException(
                status_code=409,
                detail=f"只能恢复 interrupted 或 paused 状态的 Job，当前为 {job.status}",
            )

        job.updated_at = datetime.utcnow()
        db.commit()
        new_status = job.status

    logger.info("Job %s resumed: %s → %s", job_id, job.status, new_status)

    return JobActionResponse(
        success=True,
        job_id=job_id,
        status=new_status,
        message=msg,
    )


@jobs_router.post(
    "/{job_id}/pause",
    response_model=JobActionResponse,
    summary="暂停 running Job",
)
def pause_job(job_id: str) -> JobActionResponse:
    """暂停 running 状态的 Job（在 paper 边界生效，不留半篇数据）."""
    with SessionLocal() as db:
        job = _get_job_or_404(db, job_id)

        if job.status != JobStatus.RUNNING.value:
            raise HTTPException(
                status_code=409,
                detail=f"只能暂停 running 状态的 Job，当前为 {job.status}",
            )

        job.status = JobStatus.PAUSED.value
        job.updated_at = datetime.utcnow()
        db.commit()

    return JobActionResponse(
        success=True,
        job_id=job_id,
        status=JobStatus.PAUSED.value,
        message="暂停信号已发送，将在当前文献处理完成后生效",
    )


@jobs_router.post(
    "/{job_id}/cancel",
    response_model=JobActionResponse,
    summary="取消 Job",
)
def cancel_job(job_id: str) -> JobActionResponse:
    """取消 queued/running/paused 状态的 Job（在 paper 边界生效）."""
    with SessionLocal() as db:
        job = _get_job_or_404(db, job_id)

        if job.status not in (
            JobStatus.QUEUED.value,
            JobStatus.RUNNING.value,
            JobStatus.PAUSED.value,
            JobStatus.INTERRUPTED.value,
        ):
            raise HTTPException(
                status_code=409,
                detail=f"Job 当前状态 {job.status} 不可取消",
            )

        job.status = JobStatus.CANCELLED.value
        job.updated_at = datetime.utcnow()
        db.commit()

    return JobActionResponse(
        success=True,
        job_id=job_id,
        status=JobStatus.CANCELLED.value,
        message="取消信号已发送，将在当前文献处理完成后生效",
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/clustering/limitation — 局限聚类（Step4）
# ---------------------------------------------------------------------------


class LimitationClusterRequest(BaseModel):
    """局限聚类请求."""
    force: bool = Field(False, description="是否忽略缓存强制重跑（当前版本暂不缓存）")


class EvidenceItem(BaseModel):
    """候选组内单条证据（含 subject 透传 — ADR-7 命脉）."""
    claim_id: str
    paper_id: str
    paper_title: str
    subject: str = ""           # ADR-7 命脉：研究对象（如 "hiPSC-derived RPE cells"）
    topic: str
    quote: str
    page: int
    context: str = ""


class AdjudicationBlock(BaseModel):
    """裁决状态块（人裁决前全部为 pending + null）."""
    status: str = "pending"
    signal_name: Optional[str] = None
    human_rationale: Optional[str] = None
    reviewed_at: Optional[str] = None


class CandidateGroupItem(BaseModel):
    """一个候选组的完整信息."""
    candidate_group_id: int
    topic: str
    group_label: str
    grouping_method: str
    grouping_basis: str
    cross_paper: bool
    paper_count: int
    claim_count: int
    adjudication: AdjudicationBlock
    evidence: list[EvidenceItem]


class LimitationClusterResponse(BaseModel):
    """局限聚类 API 响应."""
    model_config = {"protected_namespaces": ()}
    project_id: str
    run_id: str = ""               # Step5: 落库后返回批次 ID，空串表示未落库
    total_claims: int
    total_candidate_groups: int
    model_used: str
    wall_time_seconds: float
    groups: list[CandidateGroupItem]


# 聚类总超时：留 2s buffer 给 HTTP 往返
_CLUSTERING_TIMEOUT = 28.0


@router.post(
    "/{project_id}/clustering/limitation",
    response_model=LimitationClusterResponse,
    summary="局限聚类 — 对项目内 is_limitation 的 claims 聚类为候选组",
)
async def cluster_limitations(
    project_id: str,
    body: LimitationClusterRequest = LimitationClusterRequest(),
    db: Session = Depends(get_db),
) -> LimitationClusterResponse:
    """同步执行局限聚类，对项目内所有 is_limitation=true 的 claims 聚类。

    流程：
    1. 校验项目存在
    2. 读取该项目下所有 is_limitation 的 claims
    3. 按 topic 确定性分桶
    4. 每个 topic 内调 LLM 做分组辅助
    5. 聚类完成后自动落库（candidate_groups + candidate_group_claims）
    6. 返回候选组列表 + evidence + run_id

    ADR-7 合规：
    - 输出为候选组 + 完整证据清单，无 signal_name / confidence
    - 每条 evidence 含 subject（区分 "RPE65 vs 光感受器"）
    - 裁决状态 = pending，等待人裁决
    - 不碰 signals 表（信号由人裁决后产生）

    超时处理：
    - 快模型 < 30秒：同步返回结果
    - 慢模型超时：返回 504 错误，提示用户使用更快模型重试
    """
    # 校验项目存在
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")

    # 检查是否有 claims
    paper_ids = [
        row[0]
        for row in db.query(Paper.id).filter(Paper.project_id == project_id).all()
    ]
    if not paper_ids:
        return LimitationClusterResponse(
            project_id=project_id,
            run_id="",
            total_claims=0,
            total_candidate_groups=0,
            model_used=_get_model_name_safe(),
            wall_time_seconds=0,
            groups=[],
        )

    from backend.services.limitation_clusterer import run_clustering
    from backend.services.cluster_writer import save_clustering_result

    logger.info("开始局限聚类: project_id=%s", project_id)

    try:
        result = await asyncio.wait_for(
            run_clustering(project_id),
            timeout=_CLUSTERING_TIMEOUT,
        )
    except ValueError as exc:
        # Key 未配置等配置错误 → 友好 400 而非 500
        raise HTTPException(status_code=400, detail=str(exc))
    except asyncio.TimeoutError:
        model_name = _get_model_name_safe()
        logger.error(
            "局限聚类超时 (%.0fs): project_id=%s model=%s",
            _CLUSTERING_TIMEOUT, project_id, model_name,
        )
        raise HTTPException(
            status_code=504,
            detail=(
                f"局限聚类超时（{_CLUSTERING_TIMEOUT:.0f} 秒）。"
                f"当前模型 {model_name} 可能过慢，建议在设置中切换为更快模型"
                f"（如 kimi-k2.6 / moonshot-v1-8k / deepseek-chat）后重试。"
            ),
        )
    except Exception as exc:
        logger.exception("局限聚类失败: project_id=%s", project_id)
        raise HTTPException(
            status_code=500,
            detail=f"局限聚类失败: {str(exc)[:300]}",
        )

    # Step5: 聚类完成后自动落库（事务性写入 candidate_groups + candidate_group_claims）
    run_id = ""
    if result.get("groups"):
        try:
            run_id = save_clustering_result(result)
            logger.info("聚类结果已落库: run_id=%s", run_id[:12])
        except Exception as exc:
            logger.exception("落库失败（聚类结果仍返回）: %s", exc)
            # 落库失败不阻塞 API 响应，但 run_id 留空提示
    result["run_id"] = run_id

    return LimitationClusterResponse(**result)


__all__ = ["router", "estimate_router", "jobs_router"]
