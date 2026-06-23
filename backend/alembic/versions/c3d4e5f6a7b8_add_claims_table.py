"""add claims table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等守卫：如果 claims 表已存在（通常通过 fallback create_all 创建），则跳过
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    if "claims" in inspector.get_table_names():
        return
    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=False),
        sa.Column("claim_form", sa.String(length=20), nullable=False),
        sa.Column("topic", sa.String(length=20), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=True),
        sa.Column("comparison_result", sa.String(length=20), nullable=True),
        sa.Column("magnitude", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("stat_support", sa.Boolean(), nullable=False),
        sa.Column("is_limitation", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("quote", sa.String(length=300), nullable=False),
        sa.Column("quote_page", sa.Integer(), nullable=False),
        sa.Column("extraction_source", sa.String(length=20), nullable=False, server_default="model"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "claim_form IN ('effect', 'state', 'characterization', 'comparison')",
            name="ck_claims_claim_form",
        ),
        sa.CheckConstraint(
            "topic IS NULL OR topic IN ('efficacy', 'safety', 'manufacturing', 'mechanism', 'other')",
            name="ck_claims_topic",
        ),
        sa.CheckConstraint(
            "extraction_source IN ('model', 'human_verified')",
            name="ck_claims_extraction_source",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"],
            ondelete="CASCADE", name="fk_claims_paper_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_claims"),
    )
    op.create_index("ix_claims_paper_id", "claims", ["paper_id"])
    op.create_index("ix_claims_claim_form", "claims", ["claim_form"])
    op.create_index("ix_claims_topic", "claims", ["topic"])
    op.create_index("ix_claims_is_limitation", "claims", ["is_limitation"])


def downgrade() -> None:
    op.drop_table("claims")
