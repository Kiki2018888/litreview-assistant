"""应用配置中心.

所有配置项支持从环境变量读取（前缀 RA_），未设置时使用默认值。
与 SPEC §7 中的配置完全一致。

路径规则：
- 开发模式（Python 直接运行）：数据目录为项目根下的 data/
- 生产模式（PyInstaller 打包）：数据目录为用户应用数据目录
  （Windows %APPDATA%/ResearchAssistant/data/，
   macOS ~/Library/Application Support/ResearchAssistant/data/，
   Linux ~/.local/share/ResearchAssistant/data/）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# 运行时路径解析
# ---------------------------------------------------------------------------


def _get_app_data_dir() -> Path:
    """获取用户应用数据目录（生产模式）或项目目录（开发模式）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后：使用系统用户数据目录（有写入权限）
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        return base / "ResearchAssistant" / "data"
    else:
        # 开发模式：项目根目录下的 data/
        return Path(__file__).resolve().parents[1] / "data"


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = _get_app_data_dir()
PDF_DIR = DATA_DIR / "papers"
DB_PATH = DATA_DIR / "research-assistant.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"


def _ensure_dirs() -> None:
    """确保项目所需的运行时目录存在."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)


# 模块导入时自动创建目录
_ensure_dirs()


# ---------------------------------------------------------------------------
# 应用级常量（非配置项）
# ---------------------------------------------------------------------------

VERSION = "1.2.0"

# .env 文件路径：显式锚定绝对路径，不依赖 cwd。
# - 开发模式：项目根/.env
# - frozen 模式：%APPDATA%/ResearchAssistant/.env（DATA_DIR 在 data/ 子目录下）
_ENV_FILE = str(DATA_DIR.parent / ".env") if getattr(sys, "frozen", False) else str(_PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# Pydantic Settings：环境变量可覆盖的配置
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """可覆盖的应用配置，环境变量前缀 RA_.

    例如：RA_DEFAULT_MODEL=kimi-k2-5 可覆盖默认模型。
    """

    model_config = SettingsConfigDict(
        env_prefix="RA_",
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Kimi API ----
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    default_model: str = "moonshot-v1-128k"
    available_models: list[str] = [
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
        "kimi-k2.6",
        "kimi-k2-6",
    ]
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_default_model: str = "deepseek-v4-pro"
    default_temperature: float = 0.3
    default_max_tokens: int = 8192
    request_timeout: int = 120

    # ---- 批量提取 ----
    batch_extract_concurrency: int = 1  # MVP 串行

    # ---- 文件上传限制 ----
    max_upload_file_size_mb: int = 50
    max_upload_file_count: int = 50

    # ---- 重试策略 ----
    max_retries: int = 3
    retry_base_delay: float = 1.0  # 秒，指数退避：1 → 2 → 4

    # ---- 扫描版检测 ----
    scanned_page_min_chars: int = 50

    # ---- 后端服务 ----
    host: str = "127.0.0.1"
    port: int = 8000

    # ---- 开发调试 ----
    debug: bool = False


# 单例
settings = Settings()


# ---------------------------------------------------------------------------
# 便捷导出（兼容直接 import 的写法）
# ---------------------------------------------------------------------------

KIMI_BASE_URL = settings.kimi_base_url
DEFAULT_MODEL = settings.default_model
AVAILABLE_MODELS = settings.available_models
DEFAULT_TEMPERATURE = settings.default_temperature
DEFAULT_MAX_TOKENS = settings.default_max_tokens
REQUEST_TIMEOUT = settings.request_timeout
BATCH_EXTRACT_CONCURRENCY = settings.batch_extract_concurrency
MAX_RETRIES = settings.max_retries
RETRY_BASE_DELAY = settings.retry_base_delay
SCANNED_PAGE_MIN_CHARS = settings.scanned_page_min_chars
MAX_UPLOAD_FILE_SIZE_MB = settings.max_upload_file_size_mb
MAX_UPLOAD_FILE_COUNT = settings.max_upload_file_count
DEEPSEEK_BASE_URL = settings.deepseek_base_url
DEEPSEEK_DEFAULT_MODEL = settings.deepseek_default_model

__all__ = [
    # 路径
    "PROJECT_ROOT",
    "DATA_DIR",
    "PDF_DIR",
    "DB_PATH",
    "DATABASE_URL",
    # 常量
    "VERSION",
    # 配置单例
    "settings",
    # 便捷导出
    "KIMI_BASE_URL",
    "DEFAULT_MODEL",
    "AVAILABLE_MODELS",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_MAX_TOKENS",
    "REQUEST_TIMEOUT",
    "BATCH_EXTRACT_CONCURRENCY",
    "MAX_RETRIES",
    "RETRY_BASE_DELAY",
    "SCANNED_PAGE_MIN_CHARS",
    "MAX_UPLOAD_FILE_SIZE_MB",
    "MAX_UPLOAD_FILE_COUNT",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_DEFAULT_MODEL",
]

# 项目根路径别名
PROJECT_ROOT = _PROJECT_ROOT
