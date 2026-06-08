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
BATCHES = "/api/v1/batches"


@pytest.fixture
def mock_parse_pdf(mock_parse_pdf):
    with patch_upload_session_flush():
        with patch("backend.api.v1.literature_crud.parse_pdf", return_value=mock_parse_pdf):
            with patch("backend.api.v1.literature_crud.asyncio.to_thread", side_effect=run_sync_to_thread):
                yield mock_parse_pdf


def _mock_json_response():
    return json.dumps({
        "background": "BG",
        "methods": "Methods",
        "key_results": ["R1"],
        "conclusion": "Conclusion",
        "keywords": ["k1", "k2"],
    })


class TestBatchExtract:
    """POST /api/v1/batches/batch-extract."""

    def test_batch_extract_with_papers(self, client, db_session, mock_parse_pdf):
        """批量提取 SSE 进度流."""
        r1 = client.post(f"{BATCHES}/", json={"name": "Extract Batch"})
        batch_id = r1.json()["id"]

        for i in range(2):
            client.post(
                f"{LIT}/upload",
                files=[("files[]", (f"p{i}.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"))],
                data={"batch_id": batch_id},
            )

        mock_client = make_kimi_client_instance(
            chat_return=make_chat_completion(_mock_json_response()),
        )

        with patch("backend.api.v1.batch_extract.KimiClient", return_value=mock_client):
            with patch("asyncio.sleep", return_value=None):
                resp = client.post(
                    f"{BATCHES}/batch-extract",
                    json={"batch_id": batch_id},
                )
                assert resp.status_code == 200
                content = resp.text
                assert "data:" in content.lower()

    def test_batch_extract_empty_batch(self, client, db_session):
        """空批次或 batch_id 无效."""
        resp = client.post(
            f"{BATCHES}/batch-extract",
            json={"batch_id": str(uuid.uuid4())},
        )
        assert resp.status_code in (200, 404)

    def test_batch_extract_no_pending(self, client, db_session, sample_batch):
        """批次无 pending 文献."""
        resp = client.post(
            f"{BATCHES}/batch-extract",
            json={"batch_id": sample_batch.id},
        )
        assert resp.status_code in (200, 404)
