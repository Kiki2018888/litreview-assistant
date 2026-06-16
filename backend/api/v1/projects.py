"""项目管理 API（v1.1.0，替代 batches）.

路由前缀: /api/v1/projects
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.v1.batch_extract import stream_project_batch_extract
from backend.models.schemas import (
    ListResponse,
    MovePapersRequest,
    MovePapersResponse,
    ProjectCreate,
    ProjectDeleteResponse,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectUpdate,
)
from backend.models.tables import Paper, Project
from backend.services.db import SessionLocal
from backend.services.project_service import (
    adjust_project_paper_count,
    get_default_project,
    move_paper_between_projects,
    recalculate_project_paper_count,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("/", response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate) -> ProjectResponse:
    """创建项目（不可创建默认项目）."""
    db = SessionLocal()
    try:
        project = Project(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            paper_count=0,
            is_default=False,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return ProjectResponse.model_validate(project)
    finally:
        db.close()


@router.get("/", response_model=ListResponse)
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ListResponse:
    """项目列表（默认项目置顶，其余按更新时间倒序）."""
    db = SessionLocal()
    try:
        total = db.scalar(select(func.count(Project.id))) or 0
        rows = (
            db.execute(
                select(Project)
                .order_by(Project.is_default.desc(), Project.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        items = [ProjectResponse.model_validate(r) for r in rows]
        return ListResponse(items=items, total=total, page=page, page_size=page_size)
    finally:
        db.close()


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: str) -> ProjectDetailResponse:
    """项目详情，含关联文献 ID 列表."""
    db = SessionLocal()
    try:
        project = _get_project_or_404(db, project_id)
        paper_ids = (
            db.execute(select(Paper.id).where(Paper.project_id == project_id))
            .scalars()
            .all()
        )
        base = ProjectResponse.model_validate(project)
        return ProjectDetailResponse(**base.model_dump(), paper_ids=list(paper_ids))
    finally:
        db.close()


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, body: ProjectUpdate) -> ProjectResponse:
    """更新项目名称或描述（默认项目不可改名）."""
    db = SessionLocal()
    try:
        project = _get_project_or_404(db, project_id)
        if project.is_default and body.name is not None and body.name != project.name:
            raise HTTPException(status_code=400, detail="默认项目「我的文献」不可重命名")

        update_data = body.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(project, key, value)

        db.commit()
        db.refresh(project)
        return ProjectResponse.model_validate(project)
    finally:
        db.close()


@router.delete("/{project_id}", response_model=ProjectDeleteResponse)
def delete_project(project_id: str) -> ProjectDeleteResponse:
    """删除项目：文献移入「我的文献」，不删除文献本身."""
    db = SessionLocal()
    try:
        project = _get_project_or_404(db, project_id)
        if project.is_default:
            raise HTTPException(status_code=400, detail="默认项目不可删除")

        default_project = get_default_project(db)
        papers = db.query(Paper).filter(Paper.project_id == project_id).all()
        moved_count = len(papers)

        for paper in papers:
            move_paper_between_projects(db, paper, default_project.id)

        db.delete(project)
        recalculate_project_paper_count(db, default_project.id)
        db.commit()

        return ProjectDeleteResponse(success=True, moved_count=moved_count)
    finally:
        db.close()


@router.post("/{project_id}/move-papers", response_model=MovePapersResponse)
def move_papers_to_project(
    project_id: str,
    body: MovePapersRequest,
) -> MovePapersResponse:
    """批量移动文献到指定项目."""
    db = SessionLocal()
    try:
        target = _get_project_or_404(db, project_id)
        moved = 0
        for paper_id in body.paper_ids:
            paper = db.get(Paper, paper_id)
            if not paper:
                raise HTTPException(status_code=404, detail=f"文献不存在: {paper_id}")
            if paper.project_id != target.id:
                move_paper_between_projects(db, paper, target.id)
                moved += 1

        db.commit()
        recalculate_project_paper_count(db, target.id)
        return MovePapersResponse(success=True, moved_count=moved)
    finally:
        db.close()


@router.post("/{project_id}/batch-extract")
async def project_batch_extract(project_id: str, request: Request) -> StreamingResponse:
    """一键提取该项目全部 pending 文献（SSE）."""
    return StreamingResponse(
        stream_project_batch_extract(project_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
