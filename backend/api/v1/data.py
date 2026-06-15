"""数据管理 API.

路由前缀: /api/v1/data — 仅限 localhost 访问
- GET  /db-stats    — 数据库统计（文件大小、各表记录数）
- POST /export-db   — 导出数据库文件下载
- POST /reset-db    — 重置数据库（需 confirm: true）
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.config import DB_PATH, DATA_DIR, PDF_DIR
from backend.services.db import SessionLocal, init_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data"])


# ---------------------------------------------------------------------------
# FTS5 重建（Alembic 初始化等价逻辑）
# ---------------------------------------------------------------------------

_FTS5_SQL = [
    # 虚拟表
    """CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
        title, authors, journal, keywords, background, methods, conclusion
    )""",
    # papers 表触发器
    """CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers
    BEGIN
        INSERT INTO papers_fts(rowid, title, authors, journal, keywords, background, methods, conclusion)
        VALUES (new.rowid, COALESCE(new.title, ''), COALESCE(new.authors, ''),
                COALESCE(new.journal, ''), '', '', '', '');
    END""",
    """CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers
    BEGIN
        UPDATE papers_fts
        SET title = COALESCE(new.title, ''),
            authors = COALESCE(new.authors, ''),
            journal = COALESCE(new.journal, '')
        WHERE rowid = old.rowid;
    END""",
    """CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers
    BEGIN
        DELETE FROM papers_fts WHERE rowid = old.rowid;
    END""",
    # extracted_data 表触发器
    """CREATE TRIGGER IF NOT EXISTS extracted_data_ai AFTER INSERT ON extracted_data
    BEGIN
        UPDATE papers_fts
        SET keywords = COALESCE(new.keywords, ''),
            background = COALESCE(new.background, ''),
            methods = COALESCE(new.methods, ''),
            conclusion = COALESCE(new.conclusion, '')
        WHERE rowid = (SELECT rowid FROM papers WHERE id = new.paper_id);
    END""",
    """CREATE TRIGGER IF NOT EXISTS extracted_data_au AFTER UPDATE ON extracted_data
    BEGIN
        UPDATE papers_fts
        SET keywords = COALESCE(new.keywords, ''),
            background = COALESCE(new.background, ''),
            methods = COALESCE(new.methods, ''),
            conclusion = COALESCE(new.conclusion, '')
        WHERE rowid = (SELECT rowid FROM papers WHERE id = new.paper_id);
    END""",
    """CREATE TRIGGER IF NOT EXISTS extracted_data_ad AFTER DELETE ON extracted_data
    BEGIN
        UPDATE papers_fts
        SET keywords = '', background = '', methods = '', conclusion = ''
        WHERE rowid = (SELECT rowid FROM papers WHERE id = old.paper_id);
    END""",
]


def _init_fts5() -> None:
    """创建 FTS5 虚拟表和同步触发器（等价于 Alembic upgrade head 中 FTS5 部分）.

    Base.metadata.create_all() 不涵盖 FTS5 虚拟表和触发器（这些不是 ORM 模型），
    reset-db 流程中 init_db() 之后必须额外调用本函数。
    """
    db = SessionLocal()
    try:
        for stmt in _FTS5_SQL:
            db.execute(text(stmt))
        db.commit()
        logger.info("FTS5 虚拟表和同步触发器已创建（%d 条语句）", len(_FTS5_SQL))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# localhost 守卫
# ---------------------------------------------------------------------------


def _require_localhost(request: Request) -> None:
    """拒绝非 localhost 请求."""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(
            status_code=403,
            detail="数据管理 API 仅限本地访问",
        )


# ---------------------------------------------------------------------------
# 响应体
# ---------------------------------------------------------------------------


class DbStatsResponse(BaseModel):
    """数据库统计响应."""

    db_file_size_bytes: int = 0
    db_file_size_mb: float = 0.0
    tables: dict[str, int] = Field(default_factory=dict)
    pdf_count: int = 0
    checked_at: str = ""


class ResetDbRequest(BaseModel):
    """重置数据库请求."""

    confirm: bool = Field(False, description="必须为 true 才能执行重置")


# ---------------------------------------------------------------------------
# GET /db-stats
# ---------------------------------------------------------------------------


@router.get("/db-stats", response_model=DbStatsResponse)
def get_db_stats(request: Request):
    """数据库统计：文件大小、各表记录数."""
    _require_localhost(request)

    stats: dict[str, int] = {}
    db_size = 0

    # 数据库文件大小
    if DB_PATH.exists():
        db_size = DB_PATH.stat().st_size

    # 各表记录数
    db = SessionLocal()
    try:
        table_names = [
            "papers", "paper_pages", "extracted_data", "batches",
            "paper_tags", "paper_audit_logs", "chat_sessions",
            "paper_blocks", "settings",
        ]
        for name in table_names:
            try:
                result = db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
                stats[name] = result or 0
            except Exception:
                stats[name] = 0
    finally:
        db.close()

    # PDF 文件数
    pdf_count = 0
    if PDF_DIR.exists():
        pdf_count = len(list(PDF_DIR.glob("*.pdf")))

    return DbStatsResponse(
        db_file_size_bytes=db_size,
        db_file_size_mb=round(db_size / (1024 * 1024), 2),
        tables=stats,
        pdf_count=pdf_count,
        checked_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# POST /export-db
# ---------------------------------------------------------------------------


@router.post("/export-db")
def export_db(request: Request):
    """导出数据库文件下载."""
    _require_localhost(request)

    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="数据库文件不存在")

    # WAL checkpoint: 将未写入主库的脏页刷入 .db，保证导出为完整快照。
    # PRAGMA wal_checkpoint(TRUNCATE) 返回 (busy, log, checkpointed):
    #   busy=1  → 有读锁阻塞，checkpoint 未完全推进
    #   log>0   → WAL 仍有残留帧，未全部刷入主库
    db = SessionLocal()
    try:
        result = db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()
        busy, log_frames, _ = result[0], result[1], result[2]
        incomplete = (busy != 0 or log_frames > 0)
    finally:
        db.close()

    if incomplete:
        logger.warning(
            "WAL checkpoint 未完全完成 (busy=%d, log=%d)，"
            "导出的备份可能不完整，建议无并发写入时重试",
            busy, log_frames,
        )

    # 注：前端做导出 UI 时需读取响应头 X-Checkpoint-Warning 并提示用户
    response = FileResponse(
        path=str(DB_PATH),
        filename=f"research-assistant-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.db",
        media_type="application/octet-stream",
    )
    if incomplete:
        response.headers["X-Checkpoint-Warning"] = (
            "incomplete; export may miss recent writes; retry when idle"
        )
    return response


# ---------------------------------------------------------------------------
# POST /reset-db
# ---------------------------------------------------------------------------


@router.post("/reset-db")
def reset_db(body: ResetDbRequest, request: Request):
    """重置数据库（删除 DB 和 PDF 文件后重新初始化）."""
    _require_localhost(request)

    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="重置数据库需要 confirm: true，此操作不可逆",
        )

    logger.warning("正在重置数据库和 PDF 文件...")

    # 1. 关闭所有数据库连接（通过删除文件后重建）
    # 2. 删除数据库文件
    if DB_PATH.exists():
        os.remove(str(DB_PATH))
        logger.info("已删除数据库文件: %s", DB_PATH)

    # 清理 WAL 附属文件（-wal / -shm），避免 reset 后残留孤儿文件
    for suffix in ("-wal", "-shm"):
        aux = str(DB_PATH) + suffix
        if os.path.exists(aux):
            os.remove(aux)
            logger.info("已删除 WAL 附属文件: %s", aux)

    # 3. 删除 PDF 目录
    if PDF_DIR.exists():
        shutil.rmtree(str(PDF_DIR))
        PDF_DIR.mkdir(parents=True)
        logger.info("已清空 PDF 目录: %s", PDF_DIR)

    # 4. 删除降级密钥文件（如果存在）
    from backend.services.secrets import _FALLBACK_KEY_FILE

    if _FALLBACK_KEY_FILE.exists():
        os.remove(str(_FALLBACK_KEY_FILE))

    # 5. 清除模块级缓存（Fernet / API Key）
    import backend.services.secrets as secrets_mod

    secrets_mod._cached_fernet = None
    secrets_mod._cached_api_key = None
    logger.info("已清除密钥缓存")

    # 6. 重新初始化（ORM 表）
    init_db()
    # 7. 重建 FTS5 虚拟表和同步触发器（init_db 不创建 FTS5）
    _init_fts5()
    logger.info("数据库已重新初始化（含 FTS5）")

    return {
        "success": True,
        "message": "数据库和 PDF 文件已清空并重新初始化",
        "reset_at": datetime.utcnow().isoformat(),
    }


__all__ = ["router"]
