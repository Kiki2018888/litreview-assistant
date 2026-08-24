"""discover job type + candidate type/weak/statement fields

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-08-24

S1 Signals discover:
- candidate_groups.candidate_type / statement / paper_count / is_weak
- extract_jobs.job_type CHECK includes 'discover'
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
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


def _extract_jobs_allows_discover() -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='extract_jobs'"
        )
    ).fetchone()
    if not row or not row[0]:
        return True
    return "discover" in row[0]


def upgrade() -> None:
    if not _has_column("candidate_groups", "candidate_type"):
        op.add_column(
            "candidate_groups",
            sa.Column(
                "candidate_type",
                sa.String(length=30),
                nullable=False,
                server_default="limitation_cluster",
            ),
        )
    if not _has_column("candidate_groups", "statement"):
        op.add_column(
            "candidate_groups",
            sa.Column("statement", sa.String(length=200), nullable=True),
        )
    if not _has_column("candidate_groups", "paper_count"):
        op.add_column(
            "candidate_groups",
            sa.Column(
                "paper_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not _has_column("candidate_groups", "is_weak"):
        op.add_column(
            "candidate_groups",
            sa.Column(
                "is_weak",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if not _has_index("ix_candidate_groups_type"):
        op.create_index(
            "ix_candidate_groups_type", "candidate_groups", ["candidate_type"],
        )
    if not _has_index("ix_candidate_groups_is_weak"):
        op.create_index(
            "ix_candidate_groups_is_weak", "candidate_groups", ["is_weak"],
        )

    # Backfill paper_count from distinct papers on member claims
    op.execute(sa.text("""
        UPDATE candidate_groups
        SET paper_count = (
            SELECT COUNT(DISTINCT claims.paper_id)
            FROM candidate_group_claims
            JOIN claims ON claims.id = candidate_group_claims.claim_id
            WHERE candidate_group_claims.candidate_group_id = candidate_groups.id
        )
        WHERE paper_count = 0
    """))

    op.execute(sa.text("""
        UPDATE candidate_groups
        SET is_weak = 1
        WHERE candidate_type = 'limitation_cluster'
          AND paper_count < 2
          AND is_weak = 0
    """))

    op.execute(sa.text("""
        UPDATE candidate_groups
        SET statement = substr(group_label, 1, 200)
        WHERE statement IS NULL
    """))

    if not _extract_jobs_allows_discover():
        _rebuild_extract_jobs_with_discover()


def _rebuild_extract_jobs_with_discover() -> None:
    """SQLite cannot ALTER CHECK; recreate extract_jobs with discover allowed."""
    bind = op.get_bind()
    raw_conn = bind.connection.connection  # type: ignore[union-attr]

    raw_conn.execute("PRAGMA foreign_keys=OFF")
    try:
        raw_conn.execute("""
            CREATE TABLE extract_jobs_new (
                id VARCHAR(36) NOT NULL,
                project_id VARCHAR(36) NOT NULL
                    REFERENCES projects(id) ON DELETE CASCADE,
                job_type VARCHAR(30) NOT NULL
                    CHECK (job_type IN (
                        'summary_extract', 'claims_extract',
                        'limitation_cluster', 'discover'
                    )),
                status VARCHAR(20) NOT NULL DEFAULT 'queued'
                    CHECK (status IN (
                        'queued', 'running', 'paused', 'completed',
                        'failed', 'interrupted', 'cancelled'
                    )),
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
        raw_conn.execute("""
            INSERT INTO extract_jobs_new (
                id, project_id, job_type, status, total, current,
                succeeded, failed, current_paper_id, error_summary,
                created_at, updated_at
            )
            SELECT
                id, project_id, job_type, status, total, current,
                succeeded, failed, current_paper_id, error_summary,
                created_at, updated_at
            FROM extract_jobs
        """)
        raw_conn.execute("DROP TABLE extract_jobs")
        raw_conn.execute("ALTER TABLE extract_jobs_new RENAME TO extract_jobs")
    finally:
        raw_conn.execute("PRAGMA foreign_keys=ON")

    if not _has_index("ix_extract_jobs_project_id"):
        op.create_index(
            "ix_extract_jobs_project_id", "extract_jobs", ["project_id"],
        )
    if not _has_index("ix_extract_jobs_status"):
        op.create_index("ix_extract_jobs_status", "extract_jobs", ["status"])
    if not _has_index("ix_extract_jobs_job_type"):
        op.create_index("ix_extract_jobs_job_type", "extract_jobs", ["job_type"])


def downgrade() -> None:
    if _has_index("ix_candidate_groups_is_weak"):
        op.drop_index("ix_candidate_groups_is_weak", table_name="candidate_groups")
    if _has_index("ix_candidate_groups_type"):
        op.drop_index("ix_candidate_groups_type", table_name="candidate_groups")
    if _has_column("candidate_groups", "is_weak"):
        op.drop_column("candidate_groups", "is_weak")
    if _has_column("candidate_groups", "paper_count"):
        op.drop_column("candidate_groups", "paper_count")
    if _has_column("candidate_groups", "statement"):
        op.drop_column("candidate_groups", "statement")
    if _has_column("candidate_groups", "candidate_type"):
        op.drop_column("candidate_groups", "candidate_type")
