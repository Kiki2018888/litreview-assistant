"""api_provider 多场景解析测试."""

from __future__ import annotations

from backend.services.api_provider import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_KIMI_CODING_BASE_URL,
    DEFAULT_MOONSHOT_BASE_URL,
    PROVIDER_AUTO,
    PROVIDER_CUSTOM,
    PROVIDER_DEEPSEEK,
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

    def test_sk_ambiguous_prefix_without_base_url(self):
        p, url = infer_provider("sk-abc123")
        assert p == PROVIDER_CUSTOM
        assert url == DEFAULT_MOONSHOT_BASE_URL

    def test_sk_deepseek_via_base_url(self):
        p, url = infer_provider("sk-abc123", api_base_url="https://api.deepseek.com")
        assert p == PROVIDER_DEEPSEEK
        assert url == "https://api.deepseek.com"

    def test_unknown_prefix(self):
        p, url = infer_provider("other-key")
        assert p == PROVIDER_CUSTOM
        assert url == DEFAULT_MOONSHOT_BASE_URL


class TestResolveApiConfig:
    def test_auto_ambiguous_sk_without_base_url(self):
        cfg = resolve_api_config("sk-test-key", api_provider=PROVIDER_AUTO)
        assert cfg.provider == PROVIDER_CUSTOM
        assert cfg.base_url == DEFAULT_MOONSHOT_BASE_URL

    def test_auto_deepseek_via_base_url(self):
        cfg = resolve_api_config(
            "sk-test-key",
            api_provider=PROVIDER_AUTO,
            api_base_url=DEFAULT_DEEPSEEK_BASE_URL,
        )
        assert cfg.provider == PROVIDER_DEEPSEEK
        assert cfg.base_url == DEFAULT_DEEPSEEK_BASE_URL
        assert cfg.model == "deepseek-v4-flash"

    def test_auto_deepseek_url_with_user_flash_model(self):
        cfg = resolve_api_config(
            "sk-test-key",
            api_provider=PROVIDER_AUTO,
            api_base_url=DEFAULT_DEEPSEEK_BASE_URL,
            api_model="deepseek-v4-flash",
        )
        assert cfg.model == "deepseek-v4-flash"
        assert cfg.provider == PROVIDER_DEEPSEEK

    def test_regression_auto_deepseek_url_null_model_not_moonshot(self):
        """根因复现：auto + deepseek URL + 空 model 不得回退 moonshot-v1-128k."""
        cfg = resolve_api_config(
            "sk-abc123",
            api_provider=PROVIDER_AUTO,
            api_base_url="https://api.deepseek.com",
            api_model=None,
        )
        assert cfg.model != "moonshot-v1-128k"
        assert cfg.model == "deepseek-v4-flash"
        assert cfg.provider == PROVIDER_DEEPSEEK

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

    def test_fixed_deepseek(self):
        cfg = resolve_api_config("sk-moonshot-key", api_provider=PROVIDER_DEEPSEEK)
        assert cfg.provider == PROVIDER_DEEPSEEK
        assert cfg.base_url == DEFAULT_DEEPSEEK_BASE_URL
        assert cfg.model == "deepseek-v4-flash"

    def test_explicit_deepseek_uses_user_model(self):
        cfg = resolve_api_config(
            "sk-any-key",
            api_provider=PROVIDER_DEEPSEEK,
            api_base_url=DEFAULT_DEEPSEEK_BASE_URL,
            api_model="deepseek-v4-flash",
        )
        assert cfg.provider == PROVIDER_DEEPSEEK
        assert cfg.model == "deepseek-v4-flash"
