"""add extract_jobs table

M8: 任务级抽取/聚类 Job 管理。
- job_type: summary_extract / claims_extract / limitation_cluster
- status: queued / running / paused / completed / failed / interrupted / cancelled

注意：SQLite 的 Alembic migrate 不支持 op.create_check_constraint，
且 op.execute(sa.text(...)) 会丢失 CHECK 约束。解决方案：
直接通过 op.get_bind() 获取原始 DBAPI 连接执行原始 SQL。

Revision ID: f6g7h8i9j0k1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 extract_jobs 表（含 CHECK 约束，通过原始 DBAPI 连接执行）."""
    bind = op.get_bind()
    # 获取底层 sqlite3 连接（绕过 SA 的 SQL 解析，保留 CHECK 约束）
    raw_conn = bind.connection.connection  # type: ignore[union-attr]

    # 幂等检查
    rows = raw_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='extract_jobs'"
    ).fetchall()
    if rows:
        return

    raw_conn.execute("""
        CREATE TABLE extract_jobs (
            id VARCHAR(36) NOT NULL,
            project_id VARCHAR(36) NOT NULL
                REFERENCES projects(id) ON DELETE CASCADE,
            job_type VARCHAR(30) NOT NULL
                CHECK (job_type IN ('summary_extract', 'claims_extract', 'limitation_cluster')),
            status VARCHAR(20) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'paused', 'completed',
                                  'failed', 'interrupted', 'cancelled')),
            total INTEGER NOT NULL DEFAULT 0,
            current INTEGER NOT NULL DEFAULT 0,
            succeeded INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            current_paper_id VARCHAR(36)
                REFERENCES papers(id) ON DELETE SET NULL,
            error_summary TEXT,
            created_at DATETIME NOT NULL DEFAULT (datetime('now')),
            updated_at DATETIME NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (id)
        )
    """)

    op.create_index("ix_extract_jobs_project_id", "extract_jobs", ["project_id"])
    op.create_index("ix_extract_jobs_status", "extract_jobs", ["status"])
    op.create_index("ix_extract_jobs_job_type", "extract_jobs", ["job_type"])


def downgrade() -> None:
    op.drop_table("extract_jobs")
