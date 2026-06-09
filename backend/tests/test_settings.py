"""设置 API 测试 —— 读写配置 / 加密 / 脱敏 / 连接测试."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetSettings:
    """GET /api/v1/settings."""

    def test_get_settings_default(self, client, db_session):
        """默认设置返回."""
        resp = client.get("/api/v1/settings/")
        assert resp.status_code == 200
        data = resp.json()
        assert "has_api_key" in data
        assert "default_model" in data
        assert "available_models" in data
        assert "temperature" in data
        assert "max_tokens" in data
        assert "theme" in data

    def test_get_settings_no_api_key(self, client, db_session):
        """未设置 API Key 时 has_api_key=False."""
        resp = client.get("/api/v1/settings/")
        assert resp.status_code == 200
        assert resp.json()["has_api_key"] is False


class TestUpdateSettings:
    """PUT /api/v1/settings."""

    def test_update_model_and_temp(self, client, db_session):
        """更新模型和温度."""
        resp = client.put(
            "/api/v1/settings/",
            json={"default_model": "moonshot-v1-8k", "temperature": 0.3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_model"] == "moonshot-v1-8k"
        assert data["temperature"] == 0.3

    def test_update_api_key(self, client, db_session):
        """保存 API Key 触发加密存储."""
        resp = client.put(
            "/api/v1/settings/",
            json={"api_key": "sk-test-key-12345"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_api_key"] is True
        # 脱敏预览
        assert "sk-" in data["api_key_preview"] or "*" in data["api_key_preview"]

    def test_update_api_key_masked_in_response(self, client, db_session):
        """API Key 在响应中脱敏，不暴露原文."""
        resp = client.put(
            "/api/v1/settings/",
            json={"api_key": "sk-this-is-a-very-long-key-for-testing"},
        )
        assert resp.status_code == 200
        data = resp.json()
        preview = data["api_key_preview"]
        # 脱敏后不应暴露完整 key
        assert "this-is-a-very-long-key-for-testing" not in preview

    def test_clear_api_key(self, client, db_session):
        """清空 API Key."""
        resp = client.put(
            "/api/v1/settings/",
            json={"api_key": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["has_api_key"] is False

    def test_update_theme(self, client, db_session):
        """更新主题."""
        resp = client.put("/api/v1/settings/", json={"theme": "dark"})
        assert resp.status_code == 200
        assert resp.json()["theme"] == "dark"


class TestApiKeyTest:
    """POST /api/v1/settings/test."""

    @pytest.mark.asyncio
    async def test_key_valid(self, client, db_session):
        """Mock 有效 API Key 测试."""
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "OK"

        async def _mock_create(*args, **kwargs):  # noqa: ARG001
            return mock_resp

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = _mock_create

        with patch("openai.AsyncOpenAI", return_value=mock_openai):
            resp = client.post(
                "/api/v1/settings/test",
                json={"api_key": "sk-valid"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_key_invalid(self, client, db_session):
        """Mock 无效 API Key → 401."""
        async def _mock_401(*args, **kwargs):  # noqa: ARG001
            raise Exception("401 Unauthorized")

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = _mock_401

        with patch("openai.AsyncOpenAI", return_value=mock_openai):
            resp = client.post(
                "/api/v1/settings/test",
                json={"api_key": "sk-invalid"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            assert data["valid"] is False
            assert "认证" in data["message"] or "无效" in data["message"] or "过期" in data["message"]

    def test_test_without_key(self, client, db_session):
        """未配置 Key 时测试."""
        resp = client.post("/api/v1/settings/test", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "未配置" in data["message"]


class TestFernetEncryption:
    """Fernet 加解密集成测试."""

    def test_encrypt_decrypt_roundtrip(self):
        """加密 → 解密往返."""
        from backend.services.secrets import _decrypt_api_key, _encrypt_api_key

        plain = "sk-roundtrip-test-key-abcdef"
        cipher = _encrypt_api_key(plain)
        assert isinstance(cipher, bytes)
        assert cipher != plain.encode()

        decrypted = _decrypt_api_key(cipher)
        assert decrypted == plain

    def test_mask_api_key(self):
        """脱敏显示."""
        from backend.api.v1.settings import _mask_api_key

        masked = _mask_api_key("sk-1234567890abcdefgh")
        assert masked.startswith("sk-")
        assert masked.endswith("efgh")
        assert "*" in masked
        assert "1234567890abcd" not in masked
        assert _mask_api_key("short") == "****"
        assert _mask_api_key("") == "****"


class TestSettingsPersistence:
    """设置持久化验证."""

    def test_settings_persist_after_update(self, client, db_session):
        """PUT 后 GET 返回更新值."""
        client.put(
            "/api/v1/settings/",
            json={"default_model": "persist-model", "max_tokens": 4096},
        )
        resp = client.get("/api/v1/settings/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_model"] == "persist-model"
        assert data["max_tokens"] == 4096
