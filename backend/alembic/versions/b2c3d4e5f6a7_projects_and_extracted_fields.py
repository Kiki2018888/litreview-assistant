"""batches -> projects, extracted_data new fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PROJECT_ID = "00000000-0000-4000-a000-000000000001"

_FTS_TRIGGERS = (
    "papers_ai",
    "papers_au",
    "papers_ad",
    "extracted_data_ai",
    "extracted_data_au",
    "extracted_data_ad",
)


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    ).fetchone()
    return row is not None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def _drop_fts_triggers() -> None:
    for name in _FTS_TRIGGERS:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))


def _recreate_fts_triggers() -> None:
    op.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
                INSERT INTO papers_fts(rowid, title, authors, journal, keywords, background, methods, conclusion)
                VALUES (new.rowid, COALESCE(new.title,''), COALESCE(new.authors,''),
                        COALESCE(new.journal,''), '', '', '', '');
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
                UPDATE papers_fts SET title=COALESCE(new.title,''), authors=COALESCE(new.authors,''),
                journal=COALESCE(new.journal,'') WHERE rowid=old.rowid;
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
                DELETE FROM papers_fts WHERE rowid=old.rowid;
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS extracted_data_ai AFTER INSERT ON extracted_data BEGIN
                UPDATE papers_fts SET keywords=COALESCE(new.keywords,''), background=COALESCE(new.background,''),
                methods=COALESCE(new.methods,''), conclusion=COALESCE(new.conclusion,'')
                WHERE rowid=(SELECT rowid FROM papers WHERE id=new.paper_id);
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS extracted_data_au AFTER UPDATE ON extracted_data BEGIN
                UPDATE papers_fts SET keywords=COALESCE(new.keywords,''), background=COALESCE(new.background,''),
                methods=COALESCE(new.methods,''), conclusion=COALESCE(new.conclusion,'')
                WHERE rowid=(SELECT rowid FROM papers WHERE id=new.paper_id);
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS extracted_data_ad AFTER DELETE ON extracted_data BEGIN
                UPDATE papers_fts SET keywords='', background='', methods='', conclusion=''
                WHERE rowid=(SELECT rowid FROM papers WHERE id=old.paper_id);
            END
            """
        )
    )


def upgrade() -> None:
    if not _has_column("extracted_data", "research_question"):
        with op.batch_alter_table("extracted_data", schema=None) as batch_op:
            batch_op.add_column(sa.Column("research_question", sa.Text(), nullable=True))
            batch_op.add_column(sa.Column("sample_source", sa.Text(), nullable=True))
            batch_op.add_column(sa.Column("sample_size", sa.Text(), nullable=True))
            batch_op.add_column(sa.Column("key_methods", sa.JSON(), nullable=True))
            batch_op.add_column(sa.Column("key_data", sa.JSON(), nullable=True))
            batch_op.add_column(sa.Column("limitations", sa.JSON(), nullable=True))

    if _table_exists("batches") and not _table_exists("projects"):
        op.rename_table("batches", "projects")

    if _table_exists("projects") and not _has_column("projects", "is_default"):
        with op.batch_alter_table("projects", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0")
            )

    if _table_exists("projects"):
        op.execute(
            sa.text(
                f"""
                INSERT OR IGNORE INTO projects (id, name, description, paper_count, is_default, created_at, updated_at)
                VALUES (
                    '{DEFAULT_PROJECT_ID}',
                    '我的文献',
                    NULL,
                    0,
                    1,
                    datetime('now'),
                    datetime('now')
                )
                """
            )
        )

    if _has_column("papers", "batch_id"):
        op.execute(
            sa.text(
                f"UPDATE papers SET batch_id = '{DEFAULT_PROJECT_ID}' WHERE batch_id IS NULL"
            )
        )
        _drop_fts_triggers()
        op.execute(sa.text("ALTER TABLE papers RENAME COLUMN batch_id TO project_id"))
        _recreate_fts_triggers()

        try:
            op.drop_index("ix_papers_batch_id", table_name="papers")
        except Exception:
            pass
        if not _has_column("papers", "batch_id"):
            try:
                op.create_index("ix_papers_project_id", "papers", ["project_id"], unique=False)
            except Exception:
                pass

    if _table_exists("projects"):
        op.execute(
            sa.text(
                """
                UPDATE projects
                SET paper_count = (
                    SELECT COUNT(*) FROM papers WHERE papers.project_id = projects.id
                )
                """
            )
        )


def downgrade() -> None:
    if _has_column("papers", "project_id"):
        op.execute(
            sa.text(
                f"""
                UPDATE papers
                SET project_id = NULL
                WHERE project_id IN (SELECT id FROM projects WHERE is_default = 1)
                """
            )
        )
        _drop_fts_triggers()
        op.execute(sa.text("ALTER TABLE papers RENAME COLUMN project_id TO batch_id"))
        _recreate_fts_triggers()

        try:
            op.drop_index("ix_papers_project_id", table_name="papers")
        except Exception:
            pass
        try:
            op.create_index("ix_papers_batch_id", "papers", ["batch_id"], unique=False)
        except Exception:
            pass

    if _table_exists("projects"):
        op.execute(
            sa.text(f"DELETE FROM projects WHERE id = '{DEFAULT_PROJECT_ID}'")
        )

    if _table_exists("projects") and _has_column("projects", "is_default"):
        with op.batch_alter_table("projects", schema=None) as batch_op:
            batch_op.drop_column("is_default")

    if _table_exists("projects") and not _table_exists("batches"):
        op.rename_table("projects", "batches")

    if _has_column("extracted_data", "research_question"):
        with op.batch_alter_table("extracted_data", schema=None) as batch_op:
            batch_op.drop_column("limitations")
            batch_op.drop_column("key_data")
            batch_op.drop_column("key_methods")
            batch_op.drop_column("sample_size")
            batch_op.drop_column("sample_source")
            batch_op.drop_column("research_question")
