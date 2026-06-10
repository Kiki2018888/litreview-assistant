"""Kimi 多场景 API Provider 解析与配置.

支持 Moonshot 通用平台、Kimi For Coding、自定义 endpoint 等场景。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Provider 标识
PROVIDER_AUTO = "auto"
PROVIDER_MOONSHOT = "moonshot"
PROVIDER_KIMI_CODING = "kimi-coding"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_CUSTOM = "custom"

VALID_PROVIDERS = frozenset(
    {
        PROVIDER_AUTO,
        PROVIDER_MOONSHOT,
        PROVIDER_KIMI_CODING,
        PROVIDER_DEEPSEEK,
        PROVIDER_CUSTOM,
    }
)

# 默认 endpoint（可扩展企业版/私有化时新增常量）
DEFAULT_MOONSHOT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_KIMI_CODING_BASE_URL = "https://api.kimi.com/coding/v1"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 各 Provider 推荐模型列表
MOONSHOT_MODELS = [
    "moonshot-v1-8k",
    "moonshot-v1-32k",
    "moonshot-v1-128k",
    "moonshot-v1-auto",
    "kimi-k2.5",
    "kimi-k2.6",
    "kimi-k2-5",
    "kimi-k2-6",
]
KIMI_CODING_MODELS = ["kimi-latest", "kimi-for-coding", "kimi-k2-6"]
DEEPSEEK_MODELS = ["deepseek-v4-pro", "deepseek-v4-flash"]
ALL_MODELS = list(
    dict.fromkeys(MOONSHOT_MODELS + KIMI_CODING_MODELS + DEEPSEEK_MODELS)
)


@dataclass(frozen=True)
class ResolvedApiConfig:
    """运行时解析后的 API 配置."""

    api_key: str
    provider: str
    base_url: str
    model: str


def infer_provider(api_key: str) -> tuple[str, str]:
    """根据 Key 前缀推断 provider 与默认 base_url."""
    key = (api_key or "").strip()
    if key.startswith("sk-kimi-"):
        return PROVIDER_KIMI_CODING, DEFAULT_KIMI_CODING_BASE_URL
    if key.startswith("sk-"):
        return PROVIDER_MOONSHOT, DEFAULT_MOONSHOT_BASE_URL
    return PROVIDER_CUSTOM, DEFAULT_MOONSHOT_BASE_URL


def default_base_url_for_provider(provider: str) -> str:
    """固定 provider 的默认 endpoint."""
    if provider == PROVIDER_KIMI_CODING:
        return DEFAULT_KIMI_CODING_BASE_URL
    if provider == PROVIDER_DEEPSEEK:
        return DEFAULT_DEEPSEEK_BASE_URL
    if provider == PROVIDER_MOONSHOT:
        return DEFAULT_MOONSHOT_BASE_URL
    return DEFAULT_MOONSHOT_BASE_URL


def default_model_for_provider(provider: str) -> str:
    """各 provider 的推荐默认模型."""
    if provider == PROVIDER_KIMI_CODING:
        return "kimi-k2.6"
    if provider == PROVIDER_DEEPSEEK:
        return "deepseek-v4-pro"
    return "moonshot-v1-128k"


def available_models_for_provider(provider: str) -> list[str]:
    """按 provider 返回可选模型列表."""
    if provider == PROVIDER_KIMI_CODING:
        return KIMI_CODING_MODELS.copy()
    if provider == PROVIDER_DEEPSEEK:
        return DEEPSEEK_MODELS.copy()
    if provider == PROVIDER_MOONSHOT:
        return MOONSHOT_MODELS.copy()
    return ALL_MODELS.copy()


def resolve_api_config(
    api_key: str,
    *,
    api_provider: str = PROVIDER_AUTO,
    api_base_url: Optional[str] = None,
    api_model: Optional[str] = None,
) -> ResolvedApiConfig:
    """解析最终请求配置.

    优先级：
    1. api_base_url 非空 → 作为 base_url（最高）
    2. api_provider == auto → infer_provider(api_key)
    3. api_provider 固定 → 使用对应默认 endpoint
    """
    key = (api_key or "").strip()
    if not key:
        raise ValueError("API Key 未配置")

    provider = (api_provider or PROVIDER_AUTO).strip().lower()
    if provider not in VALID_PROVIDERS:
        provider = PROVIDER_AUTO

    if provider == PROVIDER_AUTO:
        resolved_provider, base_url = infer_provider(key)
    else:
        resolved_provider = provider
        base_url = default_base_url_for_provider(provider)

    override_url = (api_base_url or "").strip()
    if override_url:
        base_url = override_url.rstrip("/")

    model = (api_model or "").strip() or default_model_for_provider(resolved_provider)

    return ResolvedApiConfig(
        api_key=key,
        provider=resolved_provider,
        base_url=base_url,
        model=model,
    )


def load_runtime_config_from_db() -> ResolvedApiConfig:
    """从数据库 settings 行加载并解析运行时 API 配置."""
    from backend.models.tables import Setting
    from backend.services.db import SessionLocal
    from backend.services.secrets import _get_decrypted_api_key

    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.id == 1).first()
        if row is None:
            raise ValueError("API Key 未配置。请前往「设置」页面输入 Kimi API Key。")
        api_key = _get_decrypted_api_key()
        if not api_key:
            raise ValueError("API Key 未配置。请前往「设置」页面输入 Kimi API Key。")
        return resolve_api_config(
            api_key,
            api_provider=row.api_provider or PROVIDER_AUTO,
            api_base_url=row.api_base_url,
            api_model=row.default_model,
        )
    finally:
        db.close()


def preview_config(
    api_key: Optional[str],
    api_provider: str = PROVIDER_AUTO,
    api_base_url: Optional[str] = None,
) -> tuple[str, str]:
    """预览 provider 与 base_url（Key 为空时仅按 provider 推断）."""
    provider = (api_provider or PROVIDER_AUTO).strip().lower()
    if provider == PROVIDER_AUTO and api_key and api_key.strip():
        p, url = infer_provider(api_key.strip())
    elif provider == PROVIDER_AUTO:
        p, url = PROVIDER_MOONSHOT, DEFAULT_MOONSHOT_BASE_URL
    else:
        p = provider
        url = default_base_url_for_provider(provider)

    override = (api_base_url or "").strip()
    if override:
        url = override.rstrip("/")
    return p, url


__all__ = [
    "PROVIDER_AUTO",
    "PROVIDER_MOONSHOT",
    "PROVIDER_KIMI_CODING",
    "PROVIDER_DEEPSEEK",
    "PROVIDER_CUSTOM",
    "ResolvedApiConfig",
    "infer_provider",
    "resolve_api_config",
    "preview_config",
    "available_models_for_provider",
    "default_base_url_for_provider",
    "default_model_for_provider",
    "DEFAULT_MOONSHOT_BASE_URL",
    "DEFAULT_KIMI_CODING_BASE_URL",
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODELS",
]
