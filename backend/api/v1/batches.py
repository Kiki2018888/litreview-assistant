"""批次管理 API.

路由前缀: /api/v1/batches
- POST   /              — 创建批次
- GET    /              — 批次列表（分页）
- GET    /{id}          — 批次详情（含关联 papers）
- PUT    /{id}          — 更新批次
- DELETE /{id}          — 删除批次（文献保留，batch_id 设为 NULL）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.models.schemas import BatchCreate, BatchResponse, BatchUpdate, ListResponse
from backend.models.tables import Batch, Paper
from backend.services.db import SessionLocal

router = APIRouter(prefix="/api/v1/batches", tags=["batches"])


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


class BatchDetailResponse(BatchResponse):
    """批次详情（含关联文献）."""

    paper_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POST / — 创建批次
# ---------------------------------------------------------------------------


@router.post("/", response_model=BatchResponse, status_code=201)
def create_batch(body: BatchCreate):
    """创建新批次."""
    db = SessionLocal()
    try:
        batch = Batch(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            paper_count=0,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        return BatchResponse.model_validate(batch)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET / — 批次列表
# ---------------------------------------------------------------------------


@router.get("/", response_model=ListResponse)
def list_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """批次列表（按创建时间倒序）."""
    db = SessionLocal()
    try:
        total = db.scalar(select(func.count(Batch.id))) or 0
        rows = (
            db.execute(
                select(Batch)
                .order_by(Batch.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        items = [BatchResponse.model_validate(r) for r in rows]
        return ListResponse(items=items, total=total, page=page, page_size=page_size)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /{id} — 批次详情
# ---------------------------------------------------------------------------


@router.get("/{batch_id}", response_model=BatchDetailResponse)
def get_batch(batch_id: str):
    """批次详情，含关联文献 ID 列表."""
    db = SessionLocal()
    try:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")

        paper_ids = (
            db.execute(
                select(Paper.id).where(Paper.batch_id == batch_id)
            )
            .scalars()
            .all()
        )

        result = BatchResponse.model_validate(batch)
        return BatchDetailResponse(
            **result.model_dump(),
            paper_ids=list(paper_ids),
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PUT /{id} — 更新批次
# ---------------------------------------------------------------------------


@router.put("/{batch_id}", response_model=BatchResponse)
def update_batch(batch_id: str, body: BatchUpdate):
    """更新批次名称或描述."""
    db = SessionLocal()
    try:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")

        update_data = body.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(batch, key, value)

        db.commit()
        db.refresh(batch)
        return BatchResponse.model_validate(batch)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DELETE /{id} — 删除批次
# ---------------------------------------------------------------------------


@router.delete("/{batch_id}")
def delete_batch(batch_id: str):
    """删除批次：文献保留，batch_id 设为 NULL，paper_count 归零."""
    db = SessionLocal()
    try:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")

        # 关联文献解除批次绑定
        db.execute(
            update(Paper)
            .where(Paper.batch_id == batch_id)
            .values(batch_id=None)
        )

        # paper_count 归零（已在 Paper.batch_id 置空时自动"脱离"，此处兜底）
        batch.paper_count = 0

        # 删除批次
        db.delete(batch)
        db.commit()

        return {"success": True, "message": f"批次 '{batch.name}' 已删除，关联文献已保留"}
    finally:
        db.close()


__all__ = ["router"]
