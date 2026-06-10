"""文献 CRUD API 测试 —— 上传 / 列表 / 详情 / 标签 / 删除 / 搜索."""

from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import patch

import pytest

from backend.models.tables import Paper
from backend.tests.helpers import patch_upload_session_flush, run_sync_to_thread

LIT = "/api/v1/literature"


@pytest.fixture
def mock_parse_pdf(mock_parse_pdf):
    """同时 patch CRUD 模块内已绑定的 parse_pdf 引用."""
    with patch_upload_session_flush():
        with patch("backend.api.v1.literature_crud.parse_pdf", return_value=mock_parse_pdf):
            with patch("backend.api.v1.literature_crud.asyncio.to_thread", side_effect=run_sync_to_thread):
                yield mock_parse_pdf


class TestUpload:
    """POST /api/v1/literature/upload."""

    def test_upload_single_pdf(self, client, mock_parse_pdf, db_session):
        """上传单个 PDF 成功."""
        resp = client.post(
            f"{LIT}/upload",
            files=[("files[]", ("test.pdf", BytesIO(b"%PDF-1.4 mock"), "application/pdf"))],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["uploaded"]) == 1
        assert data["uploaded"][0]["title"] == "Test Paper Title"

    def test_upload_multiple_pdfs(self, client, mock_parse_pdf, db_session):
        """批量上传."""
        files = [
            ("files[]", ("a.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")),
            ("files[]", ("b.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")),
        ]
        resp = client.post(f"{LIT}/upload", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["uploaded"]) == 2

    def test_upload_with_batch(self, client, mock_parse_pdf, sample_batch, db_session):
        """上传到指定批次."""
        resp = client.post(
            f"{LIT}/upload",
            files=[("files[]", ("x.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"))],
            data={"batch_id": sample_batch.id},
        )
        assert resp.status_code == 200
        paper_id = resp.json()["uploaded"][0]["id"]
        paper = db_session.query(Paper).filter(Paper.id == paper_id).first()
        assert paper.project_id == sample_batch.id

    def test_upload_non_pdf_rejected(self, client, db_session):
        """非 PDF 文件拒绝."""
        resp = client.post(
            f"{LIT}/upload",
            files=[("files[]", ("test.txt", BytesIO(b"hello"), "text/plain"))],
        )
        assert resp.status_code == 400

    def test_upload_no_files(self, client, db_session):
        """无文件 → 422."""
        resp = client.post(f"{LIT}/upload")
        assert resp.status_code == 422


class TestList:
    """GET /api/v1/literature/ — 文献列表."""

    def test_list_empty(self, client, db_session):
        """无匹配结果时返回空列表."""
        resp = client.get(f"{LIT}/?search=__pytest_no_match_xyz__")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_with_papers(self, client, sample_paper, db_session):
        """有文献时列表非空."""
        resp = client.get(f"{LIT}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_list_filter_by_status(self, client, sample_paper, sample_extracted_paper, db_session):
        """按状态筛选."""
        resp = client.get(f"{LIT}/?status=completed")
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status"] == "completed"

    def test_list_pagination(self, client, db_session):
        """分页参数."""
        resp = client.get(f"{LIT}/?page=1&page_size=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 5


class TestDetail:
    """GET /api/v1/literature/{id} 文献详情."""

    def test_get_detail(self, client, sample_paper, db_session):
        resp = client.get(f"{LIT}/{sample_paper.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sample_paper.id
        assert data["title"] == "Sample Paper"

    def test_get_nonexistent(self, client, db_session):
        resp = client.get(f"{LIT}/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_pages(self, client, sample_paper, db_session):
        resp = client.get(f"{LIT}/{sample_paper.id}/pages")
        assert resp.status_code in (200, 404)  # 无解析内容但路由存在


class TestTags:
    """标签 CRUD."""

    def test_update_tags(self, client, sample_paper, db_session):
        resp = client.put(
            f"{LIT}/{sample_paper.id}/tags",
            json={"tags": ["ml", "nlp", "transformer"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"] == ["ml", "nlp", "transformer"]

    def test_get_tags_summary(self, client, sample_paper, db_session):
        client.put(f"{LIT}/{sample_paper.id}/tags", json={"tags": ["ai"]})
        resp = client.get(f"{LIT}/tags")
        assert resp.status_code == 200
        data = resp.json()
        assert "ai" in [t["tag"] for t in data["tags"]]


class TestDelete:
    """DELETE /api/v1/literature/{id} 删除."""

    def test_delete_paper(self, client, sample_paper, db_session):
        resp = client.delete(f"{LIT}/{sample_paper.id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 确认已删除
        assert db_session.query(Paper).filter(Paper.id == sample_paper.id).first() is None

    def test_delete_nonexistent(self, client, db_session):
        resp = client.delete(f"{LIT}/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestStats:
    """GET /api/v1/literature/stats 统计."""

    def test_get_stats(self, client, sample_paper, sample_extracted_paper, db_session):
        resp = client.get(f"{LIT}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "pending" in data
        assert "completed" in data
        assert "extracting" in data


class TestFts5Search:
    """FTS5 全文搜索."""

    def test_search_by_title(self, client, sample_paper, db_session):
        resp = client.get(f"{LIT}/?search=Sample")
        assert resp.status_code == 200
        data = resp.json()
        assert any("Sample" in item.get("title", "") for item in data["items"])
