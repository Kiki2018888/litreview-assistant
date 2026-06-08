"""会话历史 API 测试 —— 列表 / 详情 / 删除."""

from __future__ import annotations

import uuid

import pytest

from backend.models.tables import ChatSession


def _create_session(db_session, session_type="literature_single", primary_paper_id=None):
    """辅助：创建会话记录."""
    sid = str(uuid.uuid4())
    session = ChatSession(
        id=sid,
        session_type=session_type,
        primary_paper_id=primary_paper_id,
        title="Test Session",
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        paper_ids=None if session_type == "literature_single" else [str(uuid.uuid4())],
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


class TestListSessions:
    """GET /api/v1/chat-sessions."""

    def test_list_empty(self, client, db_session):
        resp = client.get("/api/v1/chat-sessions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_with_sessions(self, client, db_session):
        _create_session(db_session)
        resp = client.get("/api/v1/chat-sessions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_filter_by_type(self, client, db_session):
        _create_session(db_session, session_type="literature_multi")
        _create_session(db_session, session_type="literature_single")
        resp = client.get("/api/v1/chat-sessions/?session_type=literature_multi")
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["session_type"] == "literature_multi"


class TestGetSession:
    """GET /api/v1/chat-sessions/{id}."""

    def test_get_detail(self, client, db_session):
        session = _create_session(db_session)
        resp = client.get(f"/api/v1/chat-sessions/{session.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == session.id
        assert "messages" in data

    def test_get_nonexistent(self, client, db_session):
        resp = client.get(f"/api/v1/chat-sessions/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestDeleteSession:
    """DELETE /api/v1/chat-sessions/{id}."""

    def test_delete_session(self, client, db_session):
        session = _create_session(db_session)
        resp = client.delete(f"/api/v1/chat-sessions/{session.id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 确认已删除
        assert db_session.query(ChatSession).filter(ChatSession.id == session.id).first() is None

    def test_delete_nonexistent(self, client, db_session):
        resp = client.delete(f"/api/v1/chat-sessions/{uuid.uuid4()}")
        assert resp.status_code == 404
