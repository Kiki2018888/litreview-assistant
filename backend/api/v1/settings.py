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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import (
    AVAILABLE_MODELS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    KIMI_BASE_URL,
)
from backend.models.schemas import SettingUpdate
from backend.models.tables import Setting
from backend.services.db import SessionLocal
from backend.services.secrets import (
    _cached_api_key,
    _cached_fernet,
    _decrypt_api_key,
    _encrypt_api_key,
    _get_decrypted_api_key,
    _get_fernet_key,
    _mask_api_key,
    _FALLBACK_KEY_FILE,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# 初始化 settings 行
# ---------------------------------------------------------------------------


def _ensure_settings_row(db: Session) -> Setting:
    """确保 settings 表有 id=1 的行，不存在则创建."""
    from datetime import datetime

    row = db.query(Setting).filter(Setting.id == 1).first()
    if not row:
        row = Setting(
            id=1,
            default_model=DEFAULT_MODEL,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            theme="system",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# 响应体
# ---------------------------------------------------------------------------


class SettingsDetailResponse(BaseModel):
    """完整设置响应."""

    id: int
    has_api_key: bool = False
    api_key_preview: str = ""
    default_model: Optional[str] = None
    available_models: list[str] = Field(default_factory=list)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    theme: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class ApiKeyTestRequest(BaseModel):
    """API Key 测试请求."""

    # 使用传入的 key 或已存储的 key（二选一，显式指定）
    api_key: Optional[str] = Field(None, description="要测试的 API Key（为空则测试已存储的）")


class ApiKeyTestResponse(BaseModel):
    """API Key 测试响应."""

    valid: bool
    message: str


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

        return SettingsDetailResponse(
            id=row.id,
            has_api_key=has_key,
            api_key_preview=preview,
            default_model=row.default_model,
            available_models=AVAILABLE_MODELS,
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

    db = SessionLocal()
    try:
        row = _ensure_settings_row(db)

        # API Key 更新
        if body.api_key is not None:
            if body.api_key.strip():
                row.api_key_encrypted = _encrypt_api_key(body.api_key.strip())
                secrets_mod._cached_api_key = body.api_key.strip()
            else:
                # 清空 API Key
                row.api_key_encrypted = None
                secrets_mod._cached_api_key = None

        # 其他字段
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

        has_key = bool(row.api_key_encrypted and len(row.api_key_encrypted) > 0)
        preview = ""
        if has_key:
            plain = _get_decrypted_api_key()
            if plain:
                preview = _mask_api_key(plain)
            else:
                preview = "********"

        return SettingsDetailResponse(
            id=row.id,
            has_api_key=has_key,
            api_key_preview=preview,
            default_model=row.default_model,
            available_models=AVAILABLE_MODELS,
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
    """测试 API Key 是否有效（调用 Kimi API 简单请求）."""
    from openai import AsyncOpenAI

    # 确定要测试的 key
    if body.api_key and body.api_key.strip():
        test_key = body.api_key.strip()
    else:
        test_key = _get_decrypted_api_key()
        if not test_key:
            return ApiKeyTestResponse(valid=False, message="API Key 未配置")

    client = AsyncOpenAI(
        api_key=test_key,
        base_url=KIMI_BASE_URL,
        timeout=15.0,
        max_retries=0,
    )

    try:
        response = await client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": "Hello, reply with just 'OK'."}],
            max_tokens=10,
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        if "OK" in content or len(content) > 0:
            return ApiKeyTestResponse(valid=True, message="API Key 有效，连接正常")
        return ApiKeyTestResponse(valid=True, message=f"API 响应正常: {content[:50]}")
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg:
            return ApiKeyTestResponse(valid=False, message="API Key 无效或已过期")
        if "429" in msg:
            return ApiKeyTestResponse(valid=True, message="API Key 有效但触发限流，请稍后重试")
        return ApiKeyTestResponse(valid=False, message=f"连接失败: {msg[:200]}")


__all__ = ["router"]
