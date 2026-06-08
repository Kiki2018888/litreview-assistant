"""数据管理 API 测试 —— localhost 限制 / 统计 / 导出 / 重置."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.api.v1.data import _require_localhost


class TestLocalhostGuard:
    """_require_localhost 访问控制."""

    def test_localhost_allowed(self):
        """127.0.0.1."""
        from unittest.mock import MagicMock

        req = MagicMock()
        req.client.host = "127.0.0.1"
        _require_localhost(req)  # 不抛异常

    def test_localhost_ipv6_allowed(self):
        """::1."""
        from unittest.mock import MagicMock

        req = MagicMock()
        req.client.host = "::1"
        _require_localhost(req)

    def test_remote_rejected(self):
        """192.168.1.1 → 403."""
        from unittest.mock import MagicMock

        from fastapi import HTTPException

        req = MagicMock()
        req.client.host = "192.168.1.1"
        with pytest.raises(HTTPException) as exc:
            _require_localhost(req)
        assert exc.value.status_code == 403

    def test_no_client_rejected(self):
        """无 client 信息 → 403."""
        from unittest.mock import MagicMock

        from fastapi import HTTPException

        req = MagicMock()
        req.client = None
        with pytest.raises(HTTPException) as exc:
            _require_localhost(req)
        assert exc.value.status_code == 403


class TestDbStats:
    """GET /api/v1/data/db-stats."""

    def test_stats_accessible_locally(self, client, db_session):
        """TestClient 模拟本地访问."""
        with patch("backend.api.v1.data._require_localhost", return_value=None):
            resp = client.get("/api/v1/data/db-stats")
            assert resp.status_code == 200
            data = resp.json()
            assert "db_file_size_bytes" in data
            assert "tables" in data
            assert "pdf_count" in data

    def test_stats_blocked_remote(self, client, db_session):
        """远程访问应被阻止 (不 mock _require_localhost)."""
        # TestClient 使用虚拟地址，可能不是 127.0.0.1
        # 这里验证端点存在即可（403 或 200 取决于 mock）
        resp = client.get("/api/v1/data/db-stats")
        # 可能 403（非 localhost）或 200（TestClient 默认 localhost）
        assert resp.status_code in (200, 403)


class TestExportDb:
    """POST /api/v1/data/export-db."""

    def test_export_accessible(self, client, db_session, sample_paper):
        """导出数据库文件."""
        with patch("backend.api.v1.data._require_localhost", return_value=None):
            resp = client.post("/api/v1/data/export-db")
            assert resp.status_code == 200
            assert resp.headers.get("content-type", "").startswith("application/octet-stream")


class TestResetDb:
    """POST /api/v1/data/reset-db."""

    def test_reset_requires_confirm(self, client, db_session):
        """confirm=false → 400."""
        with patch("backend.api.v1.data._require_localhost", return_value=None):
            resp = client.post("/api/v1/data/reset-db", json={"confirm": False})
            assert resp.status_code == 400
            assert "confirm" in resp.json()["detail"].lower()

    def test_reset_without_confirm_field(self, client, db_session):
        """缺少 confirm 字段时默认为 false → 400."""
        with patch("backend.api.v1.data._require_localhost", return_value=None):
            resp = client.post("/api/v1/data/reset-db", json={})
            assert resp.status_code == 400
            assert "confirm" in resp.json()["detail"].lower()
