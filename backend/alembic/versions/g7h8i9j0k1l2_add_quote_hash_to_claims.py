"""add quote_hash column to claims + backfill

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-06-17

为 claims 表新增 quote_hash 列 (CHAR(64), SHA-256)。
回填所有现有 claims 的 quote_hash（基于 normalize_text(quote)）。
"""
from collections.abc import Sequence
import hashlib

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g7h8i9j0k1l2"
down_revision: str | None = "f6g7h8i9j0k1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize_text(text: str) -> str:
    """内联 normalize_text，避免跨模块导入依赖链问题."""
    import re
    text = re.sub(r"-\n\s*", "", text)
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u2013", "-")
    text = text.replace("\u2014", "--")
    text = text.replace("\u2018", "'")
    text = text.replace("\u2019", "'")
    text = text.replace("\u201c", '"')
    text = text.replace("\u201d", '"')
    text = text.replace("\u00b0", "°")
    text = text.replace("\u00d7", "x")
    text = text.replace("\u2010", "-")
    text = text.replace("\u2011", "-")
    text = text.replace("\u2012", "-")
    text = text.replace("\u03b1", "a")
    text = text.replace("\u03b2", "b")
    text = text.replace("\u03b3", "g")
    text = text.replace("\u03b4", "d")
    text = text.replace("\u03ba", "k")
    text = text.replace("\u03bc", "u")
    text = text.replace("\u03bd", "v")
    text = text.strip()
    text = text.lower()
    return text


def _compute_hash(quote: str) -> str:
    """对 normalize_text(quote) 计算 SHA-256."""
    normalized = _normalize_text(quote)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    raw_conn = bind.connection.connection  # type: ignore[union-attr]

    # 1. 新增 quote_hash 列（幂等：列已存在则跳过）
    cols_result = raw_conn.execute("PRAGMA table_info(claims)")
    col_names = {row[1] for row in cols_result.fetchall()}
    if "quote_hash" not in col_names:
        op.execute(sa.text("ALTER TABLE claims ADD COLUMN quote_hash CHAR(64)"))
        print("[Migration g7h8i9j0k1l2] quote_hash 列已新增.")
    else:
        print("[Migration g7h8i9j0k1l2] quote_hash 列已存在，跳过 DDL.")

    # 2. 回填所有现有 claims（幂等：只填 NULL/空的）
    result = raw_conn.execute(
        "SELECT id, quote FROM claims WHERE quote_hash IS NULL OR quote_hash = ''"
    )
    rows = result.fetchall()
    if rows:
        print(f"[Migration g7h8i9j0k1l2] 回填 {len(rows)} 条 claims...")
        for claim_id, quote in rows:
            h = _compute_hash(quote or "")
            raw_conn.execute(
                "UPDATE claims SET quote_hash = ? WHERE id = ?",
                (h, claim_id),
            )
        raw_conn.commit()
        print(f"[Migration g7h8i9j0k1l2] 回填完成: {len(rows)} 条.")
    else:
        print("[Migration g7h8i9j0k1l2] 无需要回填的 claims.")


def downgrade() -> None:
    # SQLite 不支持 DROP COLUMN；回退时无操作
    pass
