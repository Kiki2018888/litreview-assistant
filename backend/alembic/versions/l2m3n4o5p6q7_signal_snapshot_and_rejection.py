"""signal snapshot fields + previously_rejected candidates

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-08-24

S2 Signals adjudication:
- signals.candidate_type / statement / evidence_snapshot / fingerprint
- candidate_groups.fingerprint / previously_rejected
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sqlite_columns(table: str) -> set[str]:
    rows = op.get_bind().execute(sa.text(f"PRAGMA table_info({table})"))
    return {row[1] for row in rows}


def _sqlite_index_names() -> set[str]:
    rows = op.get_bind().execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='index'")
    )
    return {row[0] for row in rows if row[0]}


def upgrade() -> None:
    columns_signals = _sqlite_columns("signals")
    columns_groups = _sqlite_columns("candidate_groups")
    indexes = _sqlite_index_names()
    if "candidate_type" not in columns_signals:
        op.add_column(
            "signals",
            sa.Column("candidate_type", sa.String(length=30), nullable=True),
        )
    if "statement" not in columns_signals:
        op.add_column(
            "signals",
            sa.Column("statement", sa.String(length=200), nullable=True),
        )
    if "evidence_snapshot" not in columns_signals:
        op.add_column(
            "signals",
            sa.Column("evidence_snapshot", sa.JSON(), nullable=True),
        )
    if "fingerprint" not in columns_signals:
        op.add_column(
            "signals",
            sa.Column("fingerprint", sa.String(length=64), nullable=True),
        )
    if "ix_signals_type" not in indexes:
        op.create_index("ix_signals_type", "signals", ["candidate_type"])
    if "ix_signals_fingerprint" not in indexes:
        op.create_index("ix_signals_fingerprint", "signals", ["fingerprint"])

    if "fingerprint" not in columns_groups:
        op.add_column(
            "candidate_groups",
            sa.Column("fingerprint", sa.String(length=64), nullable=True),
        )
    if "previously_rejected" not in columns_groups:
        op.add_column(
            "candidate_groups",
            sa.Column(
                "previously_rejected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "ix_candidate_groups_fingerprint" not in indexes:
        op.create_index(
            "ix_candidate_groups_fingerprint",
            "candidate_groups",
            ["fingerprint"],
        )

    # Backfill type/statement from the originating candidate group when present.
    op.execute(sa.text("""
        UPDATE signals
        SET candidate_type = (
            SELECT candidate_groups.candidate_type
            FROM candidate_groups
            WHERE candidate_groups.id = signals.candidate_group_id
        )
        WHERE candidate_type IS NULL
          AND candidate_group_id IS NOT NULL
    """))
    op.execute(sa.text("""
        UPDATE signals
        SET statement = (
            SELECT COALESCE(candidate_groups.statement, candidate_groups.group_label)
            FROM candidate_groups
            WHERE candidate_groups.id = signals.candidate_group_id
        )
        WHERE statement IS NULL
          AND candidate_group_id IS NOT NULL
    """))


def downgrade() -> None:
    columns_signals = _sqlite_columns("signals")
    columns_groups = _sqlite_columns("candidate_groups")
    indexes = _sqlite_index_names()
    if "ix_candidate_groups_fingerprint" in indexes:
        op.drop_index(
            "ix_candidate_groups_fingerprint", table_name="candidate_groups",
        )
    if "previously_rejected" in columns_groups:
        op.drop_column("candidate_groups", "previously_rejected")
    if "fingerprint" in columns_groups:
        op.drop_column("candidate_groups", "fingerprint")
    if "ix_signals_fingerprint" in indexes:
        op.drop_index("ix_signals_fingerprint", table_name="signals")
    if "ix_signals_type" in indexes:
        op.drop_index("ix_signals_type", table_name="signals")
    if "fingerprint" in columns_signals:
        op.drop_column("signals", "fingerprint")
    if "evidence_snapshot" in columns_signals:
        op.drop_column("signals", "evidence_snapshot")
    if "statement" in columns_signals:
        op.drop_column("signals", "statement")
    if "candidate_type" in columns_signals:
        op.drop_column("signals", "candidate_type")
