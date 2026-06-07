"""会话历史 API.

路由前缀: /api/v1/chat-sessions
- GET  /       — 会话列表（支持按 type 筛选，分页）
- GET  /{id}   — 会话详情（含完整 messages）
- DELETE /{id} — 删除会话
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models.schemas import ChatSessionResponse, ListResponse
from backend.models.tables import ChatSession, SessionType
from backend.services.db import SessionLocal

router = APIRouter(prefix="/api/v1/chat-sessions", tags=["chat-sessions"])


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


_VALID_TYPES = {e.value for e in SessionType}


# ---------------------------------------------------------------------------
# GET / — 会话列表
# ---------------------------------------------------------------------------


@router.get("/", response_model=ListResponse)
def list_chat_sessions(
    session_type: Optional[str] = Query(None, description="筛选会话类型"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """会话列表，支持按类型筛选，分页."""
    db = SessionLocal()
    try:
        stmt = select(ChatSession)
        count_stmt = select(func.count(ChatSession.id))

        if session_type:
            if session_type not in _VALID_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"无效的会话类型，可选值: {', '.join(sorted(_VALID_TYPES))}",
                )
            stmt = stmt.where(ChatSession.session_type == session_type)
            count_stmt = count_stmt.where(ChatSession.session_type == session_type)

        total = db.scalar(count_stmt) or 0
        rows = (
            db.execute(
                stmt.order_by(ChatSession.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        items = [ChatSessionResponse.model_validate(r) for r in rows]
        return ListResponse(items=items, total=total, page=page, page_size=page_size)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /{id} — 会话详情
# ---------------------------------------------------------------------------


@router.get("/{session_id}", response_model=ChatSessionResponse)
def get_chat_session(session_id: str):
    """会话详情（含完整 messages）."""
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        return ChatSessionResponse.model_validate(session)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DELETE /{id} — 删除会话
# ---------------------------------------------------------------------------


@router.delete("/{session_id}")
def delete_chat_session(session_id: str):
    """删除会话."""
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        db.delete(session)
        db.commit()
        return {"success": True, "message": "会话已删除"}
    finally:
        db.close()


__all__ = ["router"]
