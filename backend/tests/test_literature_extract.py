"""单篇提取 API 测试 —— 状态机 / 扫描版跳过 / SSE 流."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from backend.models.tables import Paper, PaperPage
from backend.tests.helpers import make_kimi_client_instance, make_chat_completion

LIT = "/api/v1/literature"


def _mock_extract_response():
    """返回符合 SPEC 的 JSON Mode 提取结果."""
    return json.dumps({
        "title": "Extracted Title",
        "authors": ["Author A"],
        "year": 2024,
        "journal": "Test Journal",
        "background": "This research addresses...",
        "methods": "We conducted experiments using...",
        "key_results": ["Finding 1: X improved by 30%", "Finding 2: Y decreased by 15%"],
        "conclusion": "The results demonstrate that...",
        "keywords": ["machine learning", "nlp", "transformer"],
    })


class TestExtractStatusMachine:
    """提取状态机测试."""

    def test_extract_requires_existing_paper(self, client, db_session):
        """不存在的文献 → 404."""
        resp = client.post(f"{LIT}/{uuid.uuid4()}/extract")
        assert resp.status_code == 404

    def test_extract_scanned_paper_skipped(self, client, db_session):
        """扫描版 PDF 应跳过 AI 提取."""
        pid = str(uuid.uuid4())
        paper = Paper(id=pid, file_path="/f/s.pdf", file_size=100, status="pending", is_scanned=True)
        db_session.add(paper)
        db_session.commit()

        resp = client.post(f"{LIT}/{pid}/extract")
        assert resp.status_code == 400
        assert "扫描" in resp.json()["detail"]


class TestSingleExtractSSE:
    """POST /api/v1/literature/{id}/extract SSE 流测试 (mock Kimi)."""

    def test_extract_success_sse(self, client, db_session):
        """单篇提取 SSE 流正常."""
        pid = str(uuid.uuid4())
        paper = Paper(
            id=pid, file_path="/f/t.pdf", file_size=1024, page_count=3,
            status="pending", is_scanned=False, title="Test",
        )
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperPage(
            paper_id=pid,
            page_number=1,
            text_content="Full paper text content for extraction testing.",
            char_count=45,
        ))
        db_session.commit()

        extract_json = _mock_extract_response()
        mock_client = make_kimi_client_instance(
            chat_return=make_chat_completion(extract_json),
        )

        with patch("backend.api.v1.literature_extract.KimiClient", return_value=mock_client):
            with patch("asyncio.sleep", return_value=None):
                resp = client.post(f"{LIT}/{pid}/extract")
                assert resp.status_code == 200

                content = resp.text
                assert "data:" in content.lower()

                paper = db_session.query(Paper).filter(Paper.id == pid).first()
                assert paper is not None
                assert paper.status in ("completed", "extracting", "pending")

    def test_extract_paper_with_no_content(self, client, db_session):
        """无页面内容的文献."""
        pid = str(uuid.uuid4())
        paper = Paper(
            id=pid, file_path="/f/e.pdf", file_size=1024, page_count=0,
            status="pending", is_scanned=False, title="Empty",
        )
        db_session.add(paper)
        db_session.commit()

        resp = client.post(f"{LIT}/{pid}/extract")
        assert resp.status_code == 400
