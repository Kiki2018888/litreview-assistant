"""密钥管理服务.

提供 Fernet 加密密钥的生成/存储/读取，以及 API Key 的加解密与缓存。
支持 keyring → 降级文件 → 新建三级策略。

模块级缓存（仅内存，不持久化明文）:
- _cached_fernet: Fernet 实例
- _cached_api_key: 解密后的明文 API Key
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from backend.config import DATA_DIR
from backend.services.db import SessionLocal
from backend.models.tables import Setting

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "ResearchAssistant"
_KEYRING_USERNAME = "fernet_key"
_FALLBACK_KEY_FILE = DATA_DIR / ".fernet_key"

# 模块级缓存（仅内存，不持久化明文 API Key）
_cached_fernet: Optional[Fernet] = None
_cached_api_key: Optional[str] = None  # 解密后的明文，仅内存


# ---------------------------------------------------------------------------
# Fernet 密钥管理
# ---------------------------------------------------------------------------


def _get_fernet_key() -> Fernet:
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
    f = _get_fernet_key()
    return f.encrypt(plain.encode("utf-8"))


def _decrypt_api_key(encrypted: bytes) -> str:
    """解密 API Key."""
    f = _get_fernet_key()
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
