"""批次管理 API 测试 —— CRUD / 文献关联 / 删除保留."""

from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import patch

import pytest

from backend.tests.helpers import patch_upload_session_flush, run_sync_to_thread

LIT = "/api/v1/literature"
BATCHES = "/api/v1/batches"


@pytest.fixture
def mock_parse_pdf(mock_parse_pdf):
    with patch_upload_session_flush():
        with patch("backend.api.v1.literature_crud.parse_pdf", return_value=mock_parse_pdf):
            with patch("backend.api.v1.literature_crud.asyncio.to_thread", side_effect=run_sync_to_thread):
                yield mock_parse_pdf


class TestCreateBatch:
    """POST /api/v1/batches."""

    def test_create_batch(self, client, db_session):
        resp = client.post(
            f"{BATCHES}/",
            json={"name": "NLP Papers", "description": "NLP related research"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "NLP Papers"
        assert data["paper_count"] == 0

    def test_create_batch_without_name(self, client, db_session):
        """缺少必填字段 → 422."""
        resp = client.post(f"{BATCHES}/", json={})
        assert resp.status_code == 422


class TestListBatches:
    """GET /api/v1/batches."""

    def test_list_empty(self, client, db_session):
        resp = client.get(f"{BATCHES}/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)

    def test_list_with_batch(self, client, sample_batch, db_session):
        resp = client.get(f"{BATCHES}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1


class TestGetBatch:
    """GET /api/v1/batches/{id}."""

    def test_get_batch(self, client, sample_batch, db_session):
        resp = client.get(f"{BATCHES}/{sample_batch.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Batch"

    def test_get_nonexistent(self, client, db_session):
        resp = client.get(f"{BATCHES}/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestUpdateBatch:
    """PUT /api/v1/batches/{id}."""

    def test_update_batch(self, client, sample_batch, db_session):
        resp = client.put(
            f"{BATCHES}/{sample_batch.id}",
            json={"name": "Updated Batch", "description": "Updated desc"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Batch"


class TestDeleteBatch:
    """DELETE /api/v1/batches/{id}."""

    def test_delete_batch(self, client, sample_batch, db_session):
        resp = client.delete(f"{BATCHES}/{sample_batch.id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_nonexistent(self, client, db_session):
        resp = client.delete(f"{BATCHES}/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_batch_papers_retained(self, client, db_session, mock_parse_pdf):
        """删除批次后文献保留 (batch_id → NULL)."""
        r1 = client.post(f"{BATCHES}/", json={"name": "TmpBatch"})
        batch_id = r1.json()["id"]

        r2 = client.post(
            f"{LIT}/upload",
            files=[("files[]", ("x.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"))],
            data={"batch_id": batch_id},
        )
        paper_id = r2.json()["uploaded"][0]["id"]

        r3 = client.delete(f"{BATCHES}/{batch_id}")
        assert r3.status_code == 200

        r4 = client.get(f"{LIT}/{paper_id}")
        assert r4.status_code == 200
        assert r4.json().get("batch_id") is None or r4.json().get("batch_id") == ""
