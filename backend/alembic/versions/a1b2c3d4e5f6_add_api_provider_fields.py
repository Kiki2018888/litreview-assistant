"""add api_provider and api_base_url to settings

Revision ID: a1b2c3d4e5f6
Revises: ec9feb3c397e
Create Date: 2026-06-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "ec9feb3c397e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("api_provider", sa.String(32), nullable=False, server_default="auto")
        )
        batch_op.add_column(
            sa.Column(
                "api_base_url",
                sa.String(500),
                nullable=True,
                server_default="https://api.moonshot.cn/v1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.drop_column("api_base_url")
        batch_op.drop_column("api_provider")
