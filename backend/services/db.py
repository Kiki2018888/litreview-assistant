"""数据库连接管理.

- SQLAlchemy 引擎与 SessionLocal 工厂
- SQLite PRAGMA（每连接自动执行）：
  - foreign_keys=ON    外键约束
  - journal_mode=WAL   Write-Ahead Logging，读不阻塞写
  - busy_timeout=5000  写锁等待 5 秒，防止 database is locked
- 提供 FastAPI 依赖注入函数 get_db()
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import DATA_DIR, DATABASE_URL, DB_PATH
from backend.models.tables import Base


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
    """新连接建立时应用 SQLite PRAGMA 配置（每个连接独立执行）.

    - foreign_keys=ON: 外键约束
    - journal_mode=WAL: Write-Ahead Logging，读不阻塞写
    - busy_timeout=5000: 写锁等待 5 秒，避免 database is locked
    """
    # 仅对 SQLite 生效；其他方言跳过
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
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
    # 路径常量从 backend.config 统一导入，此处仅保留兼容导出
    "DATABASE_URL",
    "DB_PATH",
    "DATA_DIR",
]
