"""add project_id to candidate_groups and signals

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-08-24

裁决数据按项目隔离：candidate_groups / signals 增加 project_id，
并从 claims→papers 回填已有行。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    """检查表是否已有某列（SQLite 兼容，PRAGMA 不支持绑定参数）."""
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def _has_index(name: str) -> bool:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='index' AND name=:name"),
        {"name": name},
    ).fetchall()
    return len(rows) > 0


def upgrade() -> None:
    if not _has_column("candidate_groups", "project_id"):
        op.add_column(
            "candidate_groups",
            sa.Column("project_id", sa.String(length=36), nullable=True),
        )
    if not _has_index("ix_candidate_groups_project_id"):
        op.create_index(
            "ix_candidate_groups_project_id", "candidate_groups", ["project_id"],
        )

    if not _has_column("signals", "project_id"):
        op.add_column(
            "signals",
            sa.Column("project_id", sa.String(length=36), nullable=True),
        )
    if not _has_index("ix_signals_project_id"):
        op.create_index("ix_signals_project_id", "signals", ["project_id"])

    # 从候选组关联的 claim → paper 回填 project_id
    op.execute(sa.text("""
        UPDATE candidate_groups
        SET project_id = (
            SELECT papers.project_id
            FROM candidate_group_claims
            JOIN claims ON claims.id = candidate_group_claims.claim_id
            JOIN papers ON papers.id = claims.paper_id
            WHERE candidate_group_claims.candidate_group_id = candidate_groups.id
              AND papers.project_id IS NOT NULL
            LIMIT 1
        )
        WHERE project_id IS NULL
    """))

    # 信号优先从所属候选组回填
    op.execute(sa.text("""
        UPDATE signals
        SET project_id = (
            SELECT candidate_groups.project_id
            FROM candidate_groups
            WHERE candidate_groups.id = signals.candidate_group_id
              AND candidate_groups.project_id IS NOT NULL
        )
        WHERE project_id IS NULL
          AND candidate_group_id IS NOT NULL
    """))

    # 无候选组（或候选组无 project_id）时，从 signal_claims → papers 回填
    op.execute(sa.text("""
        UPDATE signals
        SET project_id = (
            SELECT papers.project_id
            FROM signal_claims
            JOIN claims ON claims.id = signal_claims.claim_id
            JOIN papers ON papers.id = claims.paper_id
            WHERE signal_claims.signal_id = signals.id
              AND papers.project_id IS NOT NULL
            LIMIT 1
        )
        WHERE project_id IS NULL
    """))


def downgrade() -> None:
    if _has_index("ix_signals_project_id"):
        op.drop_index("ix_signals_project_id", table_name="signals")
    if _has_column("signals", "project_id"):
        op.drop_column("signals", "project_id")
    if _has_index("ix_candidate_groups_project_id"):
        op.drop_index("ix_candidate_groups_project_id", table_name="candidate_groups")
    if _has_column("candidate_groups", "project_id"):
        op.drop_column("candidate_groups", "project_id")
