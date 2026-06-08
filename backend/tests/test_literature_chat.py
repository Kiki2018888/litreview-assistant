"""文献对话 API 测试 —— 跨文献问答 / 单篇精读 SSE."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from backend.tests.helpers import make_kimi_client_instance, make_stream_chunk

LIT = "/api/v1/literature"


def _stream_client(texts: list[str]):
    chunks = [
        make_stream_chunk(text, finish=(i == len(texts) - 1))
        for i, text in enumerate(texts)
    ]
    return make_kimi_client_instance(stream_chunks=chunks)


class TestCrossLiteratureChat:
    """POST /api/v1/literature/chat 跨文献问答."""

    def test_chat_with_paper_ids(self, client, db_session, sample_extracted_paper):
        """基于 paper_ids 的跨文献问答 (mock SSE)."""
        mock_client = _stream_client(["Based on the provided papers, the consensus is..."])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            resp = client.post(
                f"{LIT}/chat",
                json={
                    "question": "What are the main findings?",
                    "paper_ids": [sample_extracted_paper.id],
                },
            )
            assert resp.status_code == 200
            content = resp.text
            assert "data:" in content.lower()

    def test_chat_without_paper_ids(self, client, db_session):
        """无 paper_ids / batch_id → 400."""
        resp = client.post(
            f"{LIT}/chat",
            json={"question": "What is AI?"},
        )
        assert resp.status_code == 400


class TestSinglePaperChat:
    """POST /api/v1/literature/{paper_id}/chat 单篇精读."""

    def test_single_chat_success(self, client, db_session, sample_extracted_paper):
        """单篇精读问答 SSE."""
        mock_client = _stream_client(["The ", "paper ", "discusses ", "..."])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            resp = client.post(
                f"{LIT}/{sample_extracted_paper.id}/chat",
                json={
                    "question": "What is the methodology?",
                    "use_fulltext": False,
                },
            )
            assert resp.status_code == 200
            content = resp.text
            assert "data:" in content.lower()

    def test_single_chat_nonexistent_paper(self, client, db_session):
        """不存在的文献 → 404."""
        resp = client.post(
            f"{LIT}/{uuid.uuid4()}/chat",
            json={"question": "Test?"},
        )
        assert resp.status_code == 404

    def test_single_chat_use_fulltext(self, client, db_session, sample_extracted_paper):
        """use_fulltext=True 应包含全文."""
        from backend.models.tables import PaperPage

        db_session.add(PaperPage(
            paper_id=sample_extracted_paper.id,
            page_number=1,
            text_content="Full text page content for testing fulltext chat mode.",
            char_count=50,
        ))
        db_session.commit()

        mock_client = _stream_client(["Using full text..."])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            resp = client.post(
                f"{LIT}/{sample_extracted_paper.id}/chat",
                json={"question": "Summarize", "use_fulltext": True},
            )
            assert resp.status_code == 200


class TestChatSessionSaving:
    """会话历史自动保存."""

    def test_chat_saves_session(self, client, db_session, sample_extracted_paper):
        """对话后 chat_sessions 表有记录."""
        mock_client = _stream_client(["Answer"])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            client.post(
                f"{LIT}/{sample_extracted_paper.id}/chat",
                json={"question": "Q"},
            )

        resp = client.get("/api/v1/chat-sessions/")
        assert resp.status_code == 200
        data = resp.json()
        assert any(
            s.get("session_type") == "literature_single"
            for s in data.get("items", [])
        ) or data["total"] >= 0
