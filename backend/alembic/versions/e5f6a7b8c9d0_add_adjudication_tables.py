"""add adjudication tables (candidate_groups, candidate_group_claims, signals, signal_claims)

ADR-7: AI召回候选组 + 人裁决信号

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": name},
    ).fetchall()
    return len(rows) > 0


def upgrade() -> None:
    # ----- 11. candidate_groups -----
    if not _table_exists("candidate_groups"):
        op.create_table(
            "candidate_groups",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("run_id", sa.String(36), nullable=False),
            sa.Column("group_label", sa.String(200), nullable=False),
            sa.Column("topic", sa.String(20), nullable=False),
            sa.Column("grouping_method", sa.String(50), nullable=False),
            sa.Column("grouping_basis", sa.Text, nullable=True),
            sa.Column("cross_paper", sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column("claim_count", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column(
                "created_at", sa.DateTime, nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_candidate_groups"),
        )
        op.create_index("ix_candidate_groups_run_id", "candidate_groups", ["run_id"])
        op.create_index("ix_candidate_groups_topic", "candidate_groups", ["topic"])

    # ----- 12. candidate_group_claims（FK 内联在 Column 中）-----
    if not _table_exists("candidate_group_claims"):
        op.create_table(
            "candidate_group_claims",
            sa.Column(
                "candidate_group_id", sa.String(36),
                sa.ForeignKey("candidate_groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "claim_id", sa.String(36),
                sa.ForeignKey("claims.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("claim_order", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.PrimaryKeyConstraint(
                "candidate_group_id", "claim_id",
                name="pk_candidate_group_claims",
            ),
        )
        op.create_index(
            "ix_cgroup_claims_group_id",
            "candidate_group_claims", ["candidate_group_id"],
        )

    # ----- 13. signals -----
    if not _table_exists("signals"):
        op.create_table(
            "signals",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("signal_name", sa.String(200), nullable=True),
            sa.Column(
                "status", sa.String(20), nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("topic", sa.String(20), nullable=True),
            sa.Column(
                "candidate_group_id", sa.String(36),
                sa.ForeignKey("candidate_groups.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("human_rationale", sa.Text, nullable=True),
            sa.Column("claim_count", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column(
                "created_at", sa.DateTime, nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at", sa.DateTime, nullable=False,
                server_default=sa.func.now(), onupdate=sa.func.now(),
            ),
            sa.Column("adjudicated_at", sa.DateTime, nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_signals"),
        )
        op.create_index("ix_signals_status", "signals", ["status"])
        op.create_index("ix_signals_topic", "signals", ["topic"])
        op.create_index("ix_signals_cgroup_id", "signals", ["candidate_group_id"])

    # ----- 14. signal_claims（FK 内联在 Column 中）-----
    if not _table_exists("signal_claims"):
        op.create_table(
            "signal_claims",
            sa.Column(
                "signal_id", sa.String(36),
                sa.ForeignKey("signals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "claim_id", sa.String(36),
                sa.ForeignKey("claims.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "added_by", sa.String(20), nullable=False,
                server_default=sa.text("'adopted_from_group'"),
            ),
            sa.Column(
                "added_at", sa.DateTime, nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("signal_id", "claim_id", name="pk_signal_claims"),
        )
        op.create_index("ix_signal_claims_signal_id", "signal_claims", ["signal_id"])


def downgrade() -> None:
    op.drop_table("signal_claims")
    op.drop_table("signals")
    op.drop_table("candidate_group_claims")
    op.drop_table("candidate_groups")
