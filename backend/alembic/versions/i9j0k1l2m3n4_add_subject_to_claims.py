"""add subject column to claims

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    """检查表是否已有某列（SQLite 兼容，PRAGMA 不支持绑定参数）."""
    conn = op.get_bind()
    # PRAGMA table_info 不支持参数化查询，表名必须直接拼接
    rows = conn.execute(
        sa.text(f"PRAGMA table_info({table})")
    ).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    if _has_column("claims", "subject"):
        return  # 已有 subject 列，无需操作
    op.add_column("claims", sa.Column("subject", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "subject")
