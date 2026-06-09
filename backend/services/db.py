"""数据库连接管理.

- SQLAlchemy 引擎与 SessionLocal 工厂
- 启用 SQLite 外键约束（PRAGMA foreign_keys=ON）
- 提供 FastAPI 依赖注入函数 get_db()
"""
from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.models.tables import Base


# ---------------------------------------------------------------------------
# 路径与 URL
# 与 backend.config 保持一致：生产模式用用户数据目录，开发模式用项目目录
# ---------------------------------------------------------------------------


def _get_app_data_dir() -> Path:
    """获取用户应用数据目录（生产模式）或项目目录（开发模式）。"""
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        return base / "ResearchAssistant" / "data"
    else:
        return Path(__file__).resolve().parents[2] / "data"


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _get_app_data_dir()
DB_PATH = DATA_DIR / "research-assistant.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"


def _ensure_data_dir() -> None:
    """确保 data/ 目录存在."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


# SQLite 必须关闭 same-thread 检查，FastAPI 多线程下共享连接需要
# pool_pre_ping 在长连接场景下检测失效连接
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    echo=False,
)


# ---------------------------------------------------------------------------
# 外键约束开启（每个新连接自动应用）
# ---------------------------------------------------------------------------


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # noqa: ARG001
    """新连接建立时开启 SQLite 外键约束."""
    # 仅对 SQLite 生效；其他方言跳过
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


# ---------------------------------------------------------------------------
# Session 工厂
# ---------------------------------------------------------------------------


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# FastAPI 依赖注入
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个 Session，请求结束自动关闭.

    使用方式：
        from fastapi import Depends
        from backend.services.db import get_db

        @app.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 启动辅助
# ---------------------------------------------------------------------------


def init_db() -> None:
    """创建所有表（开发用，生产请使用 Alembic 迁移）.

    谨慎调用——会绕过 Alembic 版本管理。仅在初始化或测试场景使用。
    """
    _ensure_data_dir()
    Base.metadata.create_all(bind=engine)


__all__ = [
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "DATABASE_URL",
    "DB_PATH",
    "DATA_DIR",
    "PROJECT_ROOT",
]
