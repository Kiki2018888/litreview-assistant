"""应用设置 API.

路由前缀: /api/v1/settings
- GET  /       — 获取配置（API Key 脱敏）
- PUT  /       — 更新配置（API Key Fernet 加密存储）
- POST /test   — 测试 API Key 是否有效

加密方案（参考 docs/SECURITY.md）：
- Fernet 密钥通过 keyring 存入系统 Keychain
- 密文存 SQLite settings.api_key_encrypted (BLOB)
- keyring 不可用时降级为本地文件存储
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
)
from backend.models.schemas import SettingUpdate
from backend.models.tables import Setting
from backend.services.api_provider import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_MOONSHOT_BASE_URL,
    PROVIDER_AUTO,
    PROVIDER_DEEPSEEK,
    VALID_PROVIDERS,
    available_models_for_provider,
    default_model_for_provider,
    infer_provider,
    load_runtime_config_from_db,
    resolve_api_config,
)
from backend.services.db import SessionLocal
from backend.services.secrets import (
    _cached_api_key,
    _encrypt_api_key,
    _get_decrypted_api_key,
    _mask_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Schema 迁移辅助（Alembic 不可用时的 fallback）
# ---------------------------------------------------------------------------


def _migrate_settings_columns(db: Session) -> None:
    """为已有数据库补充 api_provider / api_base_url 列."""
    rows = db.execute(text("PRAGMA table_info(settings)")).fetchall()
    colnames = {row[1] for row in rows}
    if "api_provider" not in colnames:
        db.execute(
            text(
                "ALTER TABLE settings ADD COLUMN api_provider VARCHAR(32) "
                "NOT NULL DEFAULT 'auto'"
            )
        )
    if "api_base_url" not in colnames:
        db.execute(
            text(
                "ALTER TABLE settings ADD COLUMN api_base_url VARCHAR(500) "
                f"DEFAULT '{DEFAULT_MOONSHOT_BASE_URL}'"
            )
        )
    db.commit()


# ---------------------------------------------------------------------------
# 初始化 settings 行
# ---------------------------------------------------------------------------


def _ensure_settings_row(db: Session) -> Setting:
    """确保 settings 表有 id=1 的行，不存在则创建."""
    _migrate_settings_columns(db)

    row = db.query(Setting).filter(Setting.id == 1).first()
    if not row:
        row = Setting(
            id=1,
            api_provider=PROVIDER_DEEPSEEK,
            api_base_url=DEFAULT_DEEPSEEK_BASE_URL,
            default_model=default_model_for_provider(PROVIDER_DEEPSEEK),
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            theme="system",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    else:
        if not row.api_provider:
            row.api_provider = PROVIDER_AUTO
        if not row.api_base_url:
            row.api_base_url = DEFAULT_MOONSHOT_BASE_URL
            db.commit()
            db.refresh(row)
    return row


def _build_settings_response(row: Setting, preview: str, has_key: bool) -> "SettingsDetailResponse":
    provider = row.api_provider or PROVIDER_AUTO
    models = available_models_for_provider(
        infer_provider(preview.replace("*", "sk-"))[0]
        if provider == PROVIDER_AUTO and has_key and preview
        else provider
    )
    if provider != PROVIDER_AUTO:
        models = available_models_for_provider(provider)

    return SettingsDetailResponse(
        id=row.id,
        has_api_key=has_key,
        api_key_preview=preview,
        api_provider=provider,
        api_base_url=row.api_base_url or DEFAULT_MOONSHOT_BASE_URL,
        default_model=row.default_model,
        available_models=models,
        temperature=row.temperature,
        max_tokens=row.max_tokens,
        theme=row.theme,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


# ---------------------------------------------------------------------------
# 响应体
# ---------------------------------------------------------------------------


class SettingsDetailResponse(BaseModel):
    """完整设置响应."""

    id: int
    has_api_key: bool = False
    api_key_preview: str = ""
    api_provider: str = PROVIDER_AUTO
    api_base_url: str = DEFAULT_MOONSHOT_BASE_URL
    default_model: Optional[str] = None
    available_models: list[str] = Field(default_factory=list)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    theme: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class ApiKeyTestRequest(BaseModel):
    """API Key 测试请求."""

    api_key: Optional[str] = Field(None, description="要测试的 API Key（为空则测试已存储的）")
    api_provider: Optional[str] = Field(PROVIDER_AUTO, description="auto/moonshot/kimi-coding/custom")
    api_base_url: Optional[str] = Field(None, description="手动覆盖 endpoint")


class ApiKeyTestResponse(BaseModel):
    """API Key 测试响应."""

    valid: bool
    message: str
    provider: Optional[str] = None
    base_url: Optional[str] = None


# ---------------------------------------------------------------------------
# GET / — 获取设置
# ---------------------------------------------------------------------------


@router.get("/", response_model=SettingsDetailResponse)
def get_settings():
    """获取当前配置，API Key 脱敏显示."""
    db = SessionLocal()
    try:
        row = _ensure_settings_row(db)

        has_key = bool(row.api_key_encrypted and len(row.api_key_encrypted) > 0)
        preview = ""
        if has_key:
            plain = _get_decrypted_api_key()
            if plain:
                preview = _mask_api_key(plain)
            else:
                preview = "********"

        provider = row.api_provider or PROVIDER_AUTO
        if provider == PROVIDER_AUTO and has_key:
            plain = _get_decrypted_api_key()
            resolved_provider, _ = infer_provider(plain or "")
            models = available_models_for_provider(resolved_provider)
        else:
            models = available_models_for_provider(provider)

        return SettingsDetailResponse(
            id=row.id,
            has_api_key=has_key,
            api_key_preview=preview,
            api_provider=provider,
            api_base_url=row.api_base_url or DEFAULT_MOONSHOT_BASE_URL,
            default_model=row.default_model,
            available_models=models,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
            theme=row.theme,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PUT / — 更新设置
# ---------------------------------------------------------------------------


@router.put("/", response_model=SettingsDetailResponse)
def update_settings(body: SettingUpdate):
    """更新配置，API Key 加密存储."""
    import backend.services.secrets as secrets_mod
    from backend.services.kimi_client import reset_kimi_client

    db = SessionLocal()
    try:
        row = _ensure_settings_row(db)

        if body.api_key is not None:
            if body.api_key.strip():
                row.api_key_encrypted = _encrypt_api_key(body.api_key.strip())
                secrets_mod._cached_api_key = body.api_key.strip()
            else:
                row.api_key_encrypted = None
                secrets_mod._cached_api_key = None

        if body.api_provider is not None:
            p = body.api_provider.strip().lower()
            row.api_provider = p if p in VALID_PROVIDERS else PROVIDER_AUTO

        if body.api_base_url is not None:
            row.api_base_url = body.api_base_url.strip() or None

        if body.default_model is not None:
            row.default_model = body.default_model
        if body.temperature is not None:
            row.temperature = body.temperature
        if body.max_tokens is not None:
            row.max_tokens = body.max_tokens
        if body.theme is not None:
            row.theme = body.theme

        db.commit()
        db.refresh(row)
        reset_kimi_client()

        has_key = bool(row.api_key_encrypted and len(row.api_key_encrypted) > 0)
        preview = ""
        if has_key:
            plain = _get_decrypted_api_key()
            if plain:
                preview = _mask_api_key(plain)
            else:
                preview = "********"

        provider = row.api_provider or PROVIDER_AUTO
        if provider == PROVIDER_AUTO and has_key:
            plain = _get_decrypted_api_key()
            resolved_provider, _ = infer_provider(plain or "")
            models = available_models_for_provider(resolved_provider)
        else:
            models = available_models_for_provider(provider)

        return SettingsDetailResponse(
            id=row.id,
            has_api_key=has_key,
            api_key_preview=preview,
            api_provider=provider,
            api_base_url=row.api_base_url or DEFAULT_MOONSHOT_BASE_URL,
            default_model=row.default_model,
            available_models=models,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
            theme=row.theme,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /test — 测试 API Key
# ---------------------------------------------------------------------------


@router.post("/test", response_model=ApiKeyTestResponse)
async def test_api_key(body: ApiKeyTestRequest):
    """测试 API Key 是否有效（与 Claims 提取共用 load_runtime_config_from_db）."""
    from openai import APIStatusError, AsyncOpenAI

    # 与提取路径统一：已存储 Key 时直接 load_runtime_config_from_db()
    if not (body.api_key and body.api_key.strip()):
        try:
            cfg = load_runtime_config_from_db()
        except ValueError as exc:
            return ApiKeyTestResponse(valid=False, message=str(exc))
    else:
        # 测试输入框中的新 Key：仍用 resolve_api_config，但 model 取自 DB default_model
        db = SessionLocal()
        try:
            row = _ensure_settings_row(db)
            test_key = body.api_key.strip()
            provider = (body.api_provider or row.api_provider or PROVIDER_AUTO).strip().lower()
            base_url = body.api_base_url if body.api_base_url else row.api_base_url
            try:
                cfg = resolve_api_config(
                    test_key,
                    api_provider=provider,
                    api_base_url=base_url,
                    api_model=row.default_model,
                )
            except ValueError as exc:
                return ApiKeyTestResponse(valid=False, message=str(exc))
        finally:
            db.close()

    model = cfg.model

    client = AsyncOpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=15.0,
        max_retries=0,
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello, reply with just 'OK'."}],
            max_tokens=10,
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        msg = "API Key 有效，连接正常"
        if cfg.provider == "kimi-coding":
            msg = f"已连接至 Kimi For Coding（{cfg.base_url}）"
        elif content:
            msg = f"已连接至 {cfg.provider}（{cfg.base_url}）"
        return ApiKeyTestResponse(
            valid=True,
            message=msg,
            provider=cfg.provider,
            base_url=cfg.base_url,
        )
    except APIStatusError as exc:
        status = exc.status_code
        body_text = str(exc.body) if exc.body else str(exc)
        if status in (401, 403):
            return ApiKeyTestResponse(
                valid=False,
                message="API Key 无效或已过期",
                provider=cfg.provider,
                base_url=cfg.base_url,
            )
        if status == 404 and (
            "Not found the model" in body_text
            or "resource_not_found_error" in body_text
        ):
            return ApiKeyTestResponse(
                valid=False,
                message=f"当前账号无权使用模型 {model}，请更换模型后重试",
                provider=cfg.provider,
                base_url=cfg.base_url,
            )
        if status == 429:
            return ApiKeyTestResponse(
                valid=True,
                message="API Key 有效但触发限流，请稍后重试",
                provider=cfg.provider,
                base_url=cfg.base_url,
            )
        return ApiKeyTestResponse(
            valid=False,
            message=f"连接失败 ({status}): {body_text[:200]}",
            provider=cfg.provider,
            base_url=cfg.base_url,
        )
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg or "Unauthorized" in msg:
            return ApiKeyTestResponse(
                valid=False,
                message="API Key 无效或已过期",
                provider=cfg.provider,
                base_url=cfg.base_url,
            )
        if "404" in msg and (
            "Not found the model" in msg or "resource_not_found_error" in msg
        ):
            return ApiKeyTestResponse(
                valid=False,
                message=f"当前账号无权使用模型 {model}，请更换模型后重试",
                provider=cfg.provider,
                base_url=cfg.base_url,
            )
        if "429" in msg:
            return ApiKeyTestResponse(
                valid=True,
                message="API Key 有效但触发限流，请稍后重试",
                provider=cfg.provider,
                base_url=cfg.base_url,
            )
        return ApiKeyTestResponse(
            valid=False,
            message=f"连接失败: {msg[:200]}",
            provider=cfg.provider,
            base_url=cfg.base_url,
        )


__all__ = ["router"]
