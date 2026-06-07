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

import base64
import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import (
    AVAILABLE_MODELS,
    DATA_DIR,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    KIMI_BASE_URL,
    VERSION,
)
from backend.models.schemas import SettingResponse, SettingUpdate
from backend.models.tables import Setting
from backend.services.db import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_KEYRING_SERVICE = "ResearchAssistant"
_KEYRING_USERNAME = "fernet_key"
_FALLBACK_KEY_FILE = DATA_DIR / ".fernet_key"

# 模块级缓存（仅内存，不持久化明文 API Key）
_cached_fernet: Optional[Fernet] = None
_cached_api_key: Optional[str] = None  # 解密后的明文，仅内存


# ---------------------------------------------------------------------------
# Fernet 密钥管理
# ---------------------------------------------------------------------------


def _get_fernet() -> Fernet:
    """获取 Fernet 实例（keyring → 降级 → 新建）."""
    global _cached_fernet

    if _cached_fernet is not None:
        return _cached_fernet

    key: Optional[bytes] = None

    # 1. 尝试 keyring
    try:
        import keyring  # type: ignore[import-untyped]

        raw = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if raw:
            key = raw.encode("utf-8")
            logger.debug("从 keyring 读取 Fernet 密钥成功")
    except Exception as exc:
        logger.warning("keyring 读取失败: %s，尝试降级方案", exc)

    # 2. 降级：本地文件
    if key is None and _FALLBACK_KEY_FILE.exists():
        try:
            key = _FALLBACK_KEY_FILE.read_bytes()
            logger.warning("keyring 不可用，使用本地文件存储 Fernet 密钥（安全性较低）")
        except Exception as exc:
            logger.warning("读取降级密钥文件失败: %s", exc)

    # 3. 新建密钥
    if key is None:
        key = Fernet.generate_key()
        # 尝试存入 keyring
        try:
            import keyring  # type: ignore[import-untyped]

            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key.decode("utf-8"))
            logger.info("已生成新 Fernet 密钥并存入 keyring")
        except Exception as exc:
            logger.warning("keyring 写入失败: %s，降级为本地文件", exc)
            _FALLBACK_KEY_FILE.write_bytes(key)

    _cached_fernet = Fernet(key)
    return _cached_fernet


def _encrypt_api_key(plain: str) -> bytes:
    """加密 API Key."""
    f = _get_fernet()
    return f.encrypt(plain.encode("utf-8"))


def _decrypt_api_key(encrypted: bytes) -> str:
    """解密 API Key."""
    f = _get_fernet()
    return f.decrypt(encrypted).decode("utf-8")


def _mask_api_key(key: str) -> str:
    """脱敏显示 API Key: sk-****xxxx."""
    if not key or len(key) < 10:
        return "****"
    return key[:3] + "*" * (len(key) - 7) + key[-4:]


def _get_decrypted_api_key() -> Optional[str]:
    """从数据库读取并解密 API Key."""
    global _cached_api_key
    if _cached_api_key is not None:
        return _cached_api_key

    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.id == 1).first()
        if row and row.api_key_encrypted:
            try:
                _cached_api_key = _decrypt_api_key(row.api_key_encrypted)
                return _cached_api_key
            except Exception as exc:
                logger.warning("解密 API Key 失败: %s", exc)
                return None
        return None
    finally:
        db.close()


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
    global _cached_api_key, _cached_fernet

    db = SessionLocal()
    try:
        row = _ensure_settings_row(db)

        # API Key 更新
        if body.api_key is not None:
            if body.api_key.strip():
                row.api_key_encrypted = _encrypt_api_key(body.api_key.strip())
                _cached_api_key = body.api_key.strip()
            else:
                # 清空 API Key
                row.api_key_encrypted = None
                _cached_api_key = None

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
