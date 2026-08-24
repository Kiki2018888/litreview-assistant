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


def _has_column(table: str, column: str) -> bool:
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
    if not _has_column("signals", "candidate_type"):
        op.add_column(
            "signals",
            sa.Column("candidate_type", sa.String(length=30), nullable=True),
        )
    if not _has_column("signals", "statement"):
        op.add_column(
            "signals",
            sa.Column("statement", sa.String(length=200), nullable=True),
        )
    if not _has_column("signals", "evidence_snapshot"):
        op.add_column(
            "signals",
            sa.Column("evidence_snapshot", sa.JSON(), nullable=True),
        )
    if not _has_column("signals", "fingerprint"):
        op.add_column(
            "signals",
            sa.Column("fingerprint", sa.String(length=64), nullable=True),
        )
    if not _has_index("ix_signals_type"):
        op.create_index("ix_signals_type", "signals", ["candidate_type"])
    if not _has_index("ix_signals_fingerprint"):
        op.create_index("ix_signals_fingerprint", "signals", ["fingerprint"])

    if not _has_column("candidate_groups", "fingerprint"):
        op.add_column(
            "candidate_groups",
            sa.Column("fingerprint", sa.String(length=64), nullable=True),
        )
    if not _has_column("candidate_groups", "previously_rejected"):
        op.add_column(
            "candidate_groups",
            sa.Column(
                "previously_rejected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not _has_index("ix_candidate_groups_fingerprint"):
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
    if _has_index("ix_candidate_groups_fingerprint"):
        op.drop_index(
            "ix_candidate_groups_fingerprint", table_name="candidate_groups",
        )
    if _has_column("candidate_groups", "previously_rejected"):
        op.drop_column("candidate_groups", "previously_rejected")
    if _has_column("candidate_groups", "fingerprint"):
        op.drop_column("candidate_groups", "fingerprint")
    if _has_index("ix_signals_fingerprint"):
        op.drop_index("ix_signals_fingerprint", table_name="signals")
    if _has_index("ix_signals_type"):
        op.drop_index("ix_signals_type", table_name="signals")
    if _has_column("signals", "fingerprint"):
        op.drop_column("signals", "fingerprint")
    if _has_column("signals", "evidence_snapshot"):
        op.drop_column("signals", "evidence_snapshot")
    if _has_column("signals", "statement"):
        op.drop_column("signals", "statement")
    if _has_column("signals", "candidate_type"):
        op.drop_column("signals", "candidate_type")
