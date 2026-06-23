"""add unique constraint on claims (paper_id, quote_hash)

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-06-17

给 claims 表加 (paper_id, quote_hash) 唯一约束，兜底防重复。
注意：必须先清现有重复（Migration 9 后手动清理），否则此迁移会失败。

SQLite 不支持 ALTER ADD CONSTRAINT，用 CREATE UNIQUE INDEX 替代。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h8i9j0k1l2m3"
down_revision: str | None = "g7h8i9j0k1l2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 (paper_id, quote_hash) 唯一索引（SQLite 下的唯一约束等价形式）."""
    bind = op.get_bind()

    # 幂等检查
    existing = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_claims_paper_quote_hash'")
    ).fetchall()
    if existing:
        return

    op.create_index(
        "uq_claims_paper_quote_hash",
        "claims",
        ["paper_id", "quote_hash"],
        unique=True,
    )


def downgrade() -> None:
    """移除唯一索引."""
    op.execute(sa.text("DROP INDEX IF EXISTS uq_claims_paper_quote_hash"))
