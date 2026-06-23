"""add quote_status and char_span columns to claims

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    # 幂等守卫：如果 claims 已有 quote_status 列（含 create_all 创建的全量列）
    # 则跳过此迁移，避免后半段 DROP TABLE claims 丢失后续 migration 加的列
    if _has_column("claims", "quote_status"):
        return

    with op.batch_alter_table("claims", schema=None) as batch_op:
        if not _has_column("claims", "quote_status"):
            batch_op.add_column(
                sa.Column(
                    "quote_status",
                    sa.String(20),
                    nullable=True,
                    server_default=None,
                )
            )
        if not _has_column("claims", "char_span_start"):
            batch_op.add_column(
                sa.Column("char_span_start", sa.Integer(), nullable=True)
            )
        if not _has_column("claims", "char_span_end"):
            batch_op.add_column(
                sa.Column("char_span_end", sa.Integer(), nullable=True)
            )

    # Add check constraint for quote_status (SQLite requires raw SQL after batch)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS _claims_new (
            id VARCHAR(36) NOT NULL,
            paper_id VARCHAR(36) NOT NULL,
            claim_form VARCHAR(20) NOT NULL,
            topic VARCHAR(20),
            direction VARCHAR(10),
            comparison_result VARCHAR(20),
            magnitude TEXT,
            context JSON,
            stat_support BOOLEAN NOT NULL,
            is_limitation BOOLEAN NOT NULL DEFAULT 0,
            quote VARCHAR(300) NOT NULL,
            quote_page INTEGER NOT NULL,
            extraction_source VARCHAR(20) NOT NULL DEFAULT 'model',
            notes TEXT,
            quote_status VARCHAR(20),
            char_span_start INTEGER,
            char_span_end INTEGER,
            PRIMARY KEY (id),
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
            CHECK (claim_form IN ('effect', 'state', 'characterization', 'comparison')),
            CHECK (topic IS NULL OR topic IN ('efficacy', 'safety', 'manufacturing', 'mechanism', 'other')),
            CHECK (extraction_source IN ('model', 'human_verified')),
            CHECK (quote_status IS NULL OR quote_status IN ('verified', 'unverified'))
        )
        """
    )
    # Copy data from old table to new
    op.execute("INSERT OR IGNORE INTO _claims_new SELECT * FROM claims")
    op.execute("DROP TABLE claims")
    op.execute("ALTER TABLE _claims_new RENAME TO claims")
    # Recreate indexes
    op.create_index("ix_claims_paper_id", "claims", ["paper_id"])
    op.create_index("ix_claims_claim_form", "claims", ["claim_form"])
    op.create_index("ix_claims_topic", "claims", ["topic"])
    op.create_index("ix_claims_is_limitation", "claims", ["is_limitation"])


def downgrade() -> None:
    with op.batch_alter_table("claims", schema=None) as batch_op:
        batch_op.drop_column("char_span_end")
        batch_op.drop_column("char_span_start")
        batch_op.drop_column("quote_status")
