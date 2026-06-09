"""api_provider 多场景解析测试."""

from __future__ import annotations

from backend.services.api_provider import (
    DEFAULT_KIMI_CODING_BASE_URL,
    DEFAULT_MOONSHOT_BASE_URL,
    PROVIDER_AUTO,
    PROVIDER_CUSTOM,
    PROVIDER_KIMI_CODING,
    PROVIDER_MOONSHOT,
    infer_provider,
    resolve_api_config,
)


class TestInferProvider:
    def test_sk_kimi_coding(self):
        p, url = infer_provider("sk-kimi-abc123")
        assert p == PROVIDER_KIMI_CODING
        assert url == DEFAULT_KIMI_CODING_BASE_URL

    def test_sk_moonshot(self):
        p, url = infer_provider("sk-abc123")
        assert p == PROVIDER_MOONSHOT
        assert url == DEFAULT_MOONSHOT_BASE_URL

    def test_unknown_prefix(self):
        p, url = infer_provider("other-key")
        assert p == PROVIDER_CUSTOM
        assert url == DEFAULT_MOONSHOT_BASE_URL


class TestResolveApiConfig:
    def test_auto_moonshot(self):
        cfg = resolve_api_config("sk-test-key", api_provider=PROVIDER_AUTO)
        assert cfg.provider == PROVIDER_MOONSHOT
        assert cfg.base_url == DEFAULT_MOONSHOT_BASE_URL

    def test_auto_coding(self):
        cfg = resolve_api_config("sk-kimi-test", api_provider=PROVIDER_AUTO)
        assert cfg.provider == PROVIDER_KIMI_CODING
        assert cfg.base_url == DEFAULT_KIMI_CODING_BASE_URL

    def test_fixed_moonshot(self):
        cfg = resolve_api_config("sk-kimi-x", api_provider=PROVIDER_MOONSHOT)
        assert cfg.provider == PROVIDER_MOONSHOT
        assert cfg.base_url == DEFAULT_MOONSHOT_BASE_URL

    def test_base_url_override(self):
        custom = "https://corp.example.com/v1"
        cfg = resolve_api_config(
            "sk-test",
            api_provider=PROVIDER_AUTO,
            api_base_url=custom,
        )
        assert cfg.base_url == custom
