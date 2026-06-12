"""批量提取 API 测试 —— 进度流 / 空批次 / 状态."""

from __future__ import annotations

import json
import uuid
from io import BytesIO
from unittest.mock import patch

import pytest

from backend.tests.helpers import (
    make_chat_completion,
    make_kimi_client_instance,
    patch_upload_session_flush,
    run_sync_to_thread,
)

LIT = "/api/v1/literature"
PROJECTS = "/api/v1/projects"


@pytest.fixture
def mock_parse_pdf(mock_parse_pdf):
    with patch_upload_session_flush():
        with patch("backend.api.v1.literature_crud.parse_pdf", return_value=mock_parse_pdf):
            with patch("backend.api.v1.literature_crud.asyncio.to_thread", side_effect=run_sync_to_thread):
                yield mock_parse_pdf


def _mock_json_response():
    return json.dumps({
        "title": "Batch Test",
        "research_question": "What is the effect?",
        "sample_source": "Mouse model",
        "sample_size": "n=10",
        "key_methods": ["PCR", "Western blot"],
        "key_data": ["Expression increased 2.5-fold (p<0.01)"],
        "conclusion": "Conclusion",
        "limitations": ["Small sample size"],
        "keywords": ["k1", "k2"],
        "background": "BG",
        "methods": "Methods",
        "key_results": ["R1"],
    })


class TestBatchExtract:
    """POST /api/v1/projects/{id}/batch-extract."""

    def test_batch_extract_with_papers(self, client, db_session, mock_parse_pdf):
        """批量提取 SSE 进度流."""
        r1 = client.post(f"{PROJECTS}/", json={"name": "Extract Project"})
        project_id = r1.json()["id"]

        for i in range(2):
            client.post(
                f"{LIT}/upload",
                files=[("files[]", (f"p{i}.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"))],
                data={"project_id": project_id},
            )

        mock_client = make_kimi_client_instance(
            chat_return=make_chat_completion(_mock_json_response()),
        )

        with patch("backend.api.v1.batch_extract.KimiClient", return_value=mock_client):
            with patch("asyncio.sleep", return_value=None):
                resp = client.post(f"{PROJECTS}/{project_id}/batch-extract")
                assert resp.status_code == 200
                content = resp.text
                assert "data:" in content.lower()

    def test_batch_extract_invalid_project(self, client, db_session):
        """无效 project_id."""
        resp = client.post(f"{PROJECTS}/{uuid.uuid4()}/batch-extract")
        assert resp.status_code == 200
        assert "error" in resp.text.lower() or "项目不存在" in resp.text

    def test_batch_extract_no_pending(self, client, db_session, sample_project):
        """项目无 pending 文献."""
        resp = client.post(f"{PROJECTS}/{sample_project.id}/batch-extract")
        assert resp.status_code == 200
        assert "done" in resp.text.lower()
