"""文献 AI 问答 API.

路由:
  POST /api/v1/literature/chat      — 跨文献问答
  POST /api/v1/literature/{id}/chat  — 单篇精读问答
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

from backend.config import DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS
from backend.models.tables import (
    Project,
    ChatSession,
    ExtractedData,
    Paper,
    PaperPage,
    SessionType,
)
from backend.services.db import SessionLocal
from backend.services.chat_prompt import (
    build_cross_literature_chat_prompt,
    build_single_paper_chat_prompt,
)
from backend.services.kimi_client import KimiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/literature", tags=["chat"])

_CHAT_MAX_TOKENS = DEFAULT_MAX_TOKENS


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------


class CrossLiteratureChatRequest(BaseModel):
    """跨文献问答请求."""

    question: str = Field(..., min_length=1, description="用户提问")
    paper_ids: Optional[list[str]] = Field(None, description="文献 ID 列表")
    project_id: Optional[str] = Field(None, description="项目 ID（与 paper_ids 二选一）")
    batch_id: Optional[str] = Field(None, description="已废弃，请用 project_id")
    session_id: Optional[str] = Field(None, description="会话 ID（追问用）")


class SinglePaperChatRequest(BaseModel):
    """单篇精读问答请求."""

    question: str = Field(..., min_length=1, description="用户提问")
    session_id: Optional[str] = Field(None, description="会话 ID（追问用）")
    use_fulltext: bool = Field(False, description="是否使用全文（默认使用摘要）")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _sse_msg(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_abstracts(db: Session, paper_ids: list[str]) -> list[dict]:
    """批量获取文献结构化摘要."""
    results: list[dict] = []
    for pid in paper_ids:
        paper = db.query(Paper).filter(Paper.id == pid).first()
        if not paper:
            continue
        ext = (
            db.query(ExtractedData)
            .filter(ExtractedData.paper_id == pid)
            .first()
        )
        info = {
            "paper_id": pid,
            "title": paper.title or "未命名",
            "authors": paper.authors or [],
            "year": paper.year or "未知",
        }
        if ext:
            info.update({
                "research_question": ext.research_question or ext.background or "",
                "sample_source": ext.sample_source or "",
                "sample_size": ext.sample_size or "",
                "key_methods": ext.key_methods or ([ext.methods] if ext.methods else []),
                "key_data": ext.key_data or ext.key_results or [],
                "conclusion": ext.conclusion or "",
                "limitations": ext.limitations or [],
                "keywords": ext.keywords or [],
                # 保留旧字段兼容过渡
                "background": ext.background or "",
                "methods": ext.methods or "",
                "key_results": ext.key_results or [],
            })
        results.append(info)
    return results


def _format_abstract_for_prompt(info: dict) -> str:
    """将单篇摘要格式化为 Prompt 友好的字符串（新字段优先）."""
    lines = [
        f"文献: {info.get('title', '未命名')}",
        f"作者: {', '.join(info.get('authors', [])) or '未知'}",
        f"年份: {info.get('year', '未知')}",
        f"研究问题: {info.get('research_question', '未提供')}",
        f"样本来源: {info.get('sample_source', '未提供')}",
        f"样本量: {info.get('sample_size', '未提供')}",
        f"关键技术: {'; '.join(info.get('key_methods', [])) or '未提供'}",
        f"核心数据: {'; '.join(info.get('key_data', [])) or '未提供'}",
        f"结论: {info.get('conclusion', '未提供')}",
        f"局限性: {'; '.join(info.get('limitations', [])) or '未提供'}",
        f"关键词: {', '.join(info.get('keywords', [])) or '未提供'}",
    ]
    return "\n".join(lines)


def _get_full_text(db: Session, paper_id: str) -> str:
    """拼接文献所有页面文本."""
    pages = (
        db.query(PaperPage)
        .filter(PaperPage.paper_id == paper_id)
        .order_by(PaperPage.page_number)
        .all()
    )
    return "\n\n".join(p.text_content for p in pages if p.text_content)


def _format_full_text_with_pages(db: Session, paper_id: str) -> str:
    """拼接全文，每页标注页码."""
    pages = (
        db.query(PaperPage)
        .filter(PaperPage.paper_id == paper_id)
        .order_by(PaperPage.page_number)
        .all()
    )
    lines: list[str] = []
    for p in pages:
        if p.text_content:
            lines.append(f"--- 第 {p.page_number} 页 ---")
            lines.append(p.text_content)
    return "\n".join(lines)


def _save_chat_messages(
    db: Session,
    session_id: str,
    question: str,
    answer: str,
    session_type: SessionType,
    paper_ids: Optional[list[str]] = None,
    primary_paper_id: Optional[str] = None,
) -> str:
    """保存对话消息到 chat_sessions 表（创建或追加）."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()

    new_messages = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]

    if session:
        # 追加消息
        existing = session.messages or []
        session.messages = existing + new_messages
        session.updated_at = datetime.utcnow()
    else:
        # 新建会话
        title = question[:50] if len(question) <= 50 else question[:47] + "..."
        session = ChatSession(
            id=session_id,
            session_type=session_type.value,
            paper_ids=paper_ids or [],
            primary_paper_id=primary_paper_id,
            title=title,
            messages=new_messages,
        )
        db.add(session)

    db.commit()
    return session_id


# ===================================================================
# POST /chat — 跨文献问答（固定路径，必须在 /{id}/chat 之前注册）
# ===================================================================


@router.post("/chat")
async def cross_literature_chat(body: CrossLiteratureChatRequest, request: Request):
    """跨文献问答 — 基于多篇文献摘要的 AI 综述.

    支持 paper_ids 或 batch_id 二选一指定文献范围。
    追问时传入 session_id 可自动加载历史上下文。
    """
    # 参数校验
    effective_project_id = body.project_id or body.batch_id
    if body.paper_ids and effective_project_id:
        raise HTTPException(status_code=400, detail="paper_ids 和 project_id 只能选一个")
    if not body.paper_ids and not effective_project_id:
        raise HTTPException(status_code=400, detail="必须提供 paper_ids 或 project_id")

    # 解析文献 ID 列表
    db = SessionLocal()
    try:
        if effective_project_id:
            project = db.query(Project).filter(Project.id == effective_project_id).first()
            if not project:
                raise HTTPException(status_code=404, detail="项目不存在")
            papers = (
                db.query(Paper)
                .filter(Paper.project_id == effective_project_id)
                .all()
            )
            paper_ids = [p.id for p in papers]
        else:
            paper_ids = body.paper_ids  # type: ignore[assignment]

        # 获取摘要
        abstracts = _get_abstracts(db, paper_ids)
        if not abstracts:
            raise HTTPException(status_code=400, detail="所选文献均无提取数据，请先执行 AI 提取")

        # 检查是否有未提取的文献
        missing_titles = []
        for info in abstracts:
            if not info.get("research_question") and not info.get("key_data"):
                missing_titles.append(info.get("title", "") or info["paper_id"][:8])
        if missing_titles and len(missing_titles) == len(abstracts):
            raise HTTPException(
                status_code=400,
                detail="所有文献均未提取摘要，请先对文献执行 AI 提取",
            )

        # 拼接摘要
        concatenated = "\n\n---\n\n".join(
            _format_abstract_for_prompt(a) for a in abstracts
        )
        paper_count = len(abstracts)

        # 加载历史（追问）
        history_messages = []
        if body.session_id:
            session = db.query(ChatSession).filter(
                ChatSession.id == body.session_id
            ).first()
            if session and session.messages:
                history_messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in session.messages
                ]

        # 构建系统提示
        system_prompt = build_cross_literature_chat_prompt(
            concatenated_abstracts=concatenated,
            question=body.question,
            paper_count=paper_count,
        )
    finally:
        db.close()

    # 生成或使用已有 session_id
    session_id = body.session_id or str(uuid.uuid4())
    full_answer = ""

    async def event_generator():
        nonlocal full_answer
        client = KimiClient()

        messages: list = history_messages + [
            {"role": "user", "content": system_prompt},
        ]

        try:
            async for chunk in client.chat_stream(
                messages=messages,
                model=client._model,
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=_CHAT_MAX_TOKENS,
            ):
                if await request.is_disconnected():
                    break
                full_answer += chunk
                yield _sse_msg({"type": "chunk", "content": chunk})

        except Exception as exc:
            logger.error("跨文献问答失败: %s", exc)
            yield _sse_msg({
                "type": "error",
                "code": "KIMI_API_ERROR",
                "message": f"AI 服务异常: {str(exc)[:200]}",
            })
            yield _sse_msg({"type": "done"})
            return

        # 保存对话历史
        db_save = SessionLocal()
        try:
            _save_chat_messages(
                db_save,
                session_id=session_id,
                question=body.question,
                answer=full_answer,
                session_type=SessionType.LITERATURE_MULTI,
                paper_ids=paper_ids,
            )
        finally:
            db_save.close()

        yield _sse_msg({
            "type": "result",
            "session_id": session_id,
            "answer_length": len(full_answer),
        })
        yield _sse_msg({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ===================================================================
# POST /{paper_id}/chat — 单篇精读问答
# ===================================================================


@router.post("/{paper_id}/chat")
async def single_paper_chat(
    paper_id: str,
    body: SinglePaperChatRequest,
    request: Request,
):
    """单篇精读问答 — 基于全文或摘要的深度问答.

    use_fulltext=true 时调取 paper_pages 全文（带页码标注），
    use_fulltext=false 时使用 extracted_data 结构化摘要。
    追问时传入 session_id。
    """
    db = SessionLocal()
    try:
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise HTTPException(status_code=404, detail="文献不存在")

        if body.use_fulltext:
            content = _format_full_text_with_pages(db, paper_id)
            if not content.strip():
                raise HTTPException(
                    status_code=400,
                    detail="文献全文为空，可能是解析失败。请尝试使用摘要模式。",
                )
            prompt = build_single_paper_chat_prompt(
                full_text=content,
                question=body.question,
                use_fulltext=True,
            )
        else:
            ext = (
                db.query(ExtractedData)
                .filter(ExtractedData.paper_id == paper_id)
                .first()
            )
            if not ext:
                raise HTTPException(
                    status_code=400,
                    detail="文献尚未提取摘要，请先执行 AI 提取或使用全文模式",
                )
            summary = _format_abstract_for_prompt({
                "title": paper.title or "未命名",
                "authors": paper.authors or [],
                "year": paper.year or "未知",
                "research_question": ext.research_question or ext.background or "",
                "sample_source": ext.sample_source or "",
                "sample_size": ext.sample_size or "",
                "key_methods": ext.key_methods or ([ext.methods] if ext.methods else []),
                "key_data": ext.key_data or ext.key_results or [],
                "conclusion": ext.conclusion or "",
                "limitations": ext.limitations or [],
                "keywords": ext.keywords or [],
            })
            prompt = build_single_paper_chat_prompt(
                summary=summary,
                question=body.question,
                use_fulltext=False,
            )

        # 加载历史
        history_messages = []
        if body.session_id:
            session = db.query(ChatSession).filter(
                ChatSession.id == body.session_id
            ).first()
            if session and session.messages:
                history_messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in session.messages
                ]
    finally:
        db.close()

    session_id = body.session_id or str(uuid.uuid4())
    full_answer = ""

    async def event_generator():
        nonlocal full_answer
        client = KimiClient()

        messages: list = history_messages + [
            {"role": "user", "content": prompt},
        ]

        try:
            async for chunk in client.chat_stream(
                messages=messages,
                model=client._model,
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=_CHAT_MAX_TOKENS,
            ):
                if await request.is_disconnected():
                    break
                full_answer += chunk
                yield _sse_msg({"type": "chunk", "content": chunk})

        except Exception as exc:
            logger.error("单篇精读问答失败 paper_id=%s: %s", paper_id, exc)
            yield _sse_msg({
                "type": "error",
                "code": "KIMI_API_ERROR",
                "message": f"AI 服务异常: {str(exc)[:200]}",
            })
            yield _sse_msg({"type": "done"})
            return

        # 保存
        db_save = SessionLocal()
        try:
            _save_chat_messages(
                db_save,
                session_id=session_id,
                question=body.question,
                answer=full_answer,
                session_type=SessionType.LITERATURE_SINGLE,
                paper_ids=[paper_id],
                primary_paper_id=paper_id,
            )
        finally:
            db_save.close()

        yield _sse_msg({
            "type": "result",
            "session_id": session_id,
            "answer_length": len(full_answer),
        })
        yield _sse_msg({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["router"]
