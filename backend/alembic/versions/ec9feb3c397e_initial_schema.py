"""initial_schema

Revision ID: ec9feb3c397e
Revises:
Create Date: 2026-06-05 10:58:07.165926

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ec9feb3c397e"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建初始 schema：9 张业务表 + FTS5 虚拟表 + 同步触发器.

    表结构严格遵循 SPEC 5.1 节，索引与外键 CASCADE 与 SPEC 5.3 节一致。
    FTS5 字段定义遵循 SPEC 5.2 节（7 个可搜索字段）。
    注意：FTS5 采用内部存储（省略 content='papers'），因为 7 个字段横跨
    papers 和 extracted_data 两张表，外部内容表无法跨表 JOIN。触发器负责
    维护全部 7 个字段的同步。
    """
    # ------------------------------------------------------------------
    # 1. batches — 文献批次（必须在 papers 之前，papers 有 FK 引用）
    # ------------------------------------------------------------------
    op.create_table(
        "batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("paper_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.PrimaryKeyConstraint("id", name="pk_batches"),
    )

    # ------------------------------------------------------------------
    # 2. papers — 文献元数据
    # ------------------------------------------------------------------
    op.create_table(
        "papers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("journal", sa.String(length=255), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("is_scanned", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.Column("extraction_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.CheckConstraint(
            "status IN ('pending', 'extracting', 'completed', 'failed', 'extract_failed')",
            name="ck_papers_status",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="SET NULL", name="fk_papers_batch_id"),
        sa.PrimaryKeyConstraint("id", name="pk_papers"),
    )
    op.create_index("ix_papers_title", "papers", ["title"])
    op.create_index("ix_papers_year", "papers", ["year"])
    op.create_index("ix_papers_status", "papers", ["status"])
    op.create_index("ix_papers_batch_id", "papers", ["batch_id"])

    # ------------------------------------------------------------------
    # 3. paper_pages — 按页原文
    # ------------------------------------------------------------------
    op.create_table(
        "paper_pages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE", name="fk_paper_pages_paper_id"),
        sa.PrimaryKeyConstraint("id", name="pk_paper_pages"),
        sa.UniqueConstraint("paper_id", "page_number", name="uq_paper_pages_paper_page"),
    )
    op.create_index("ix_paper_pages_paper_id", "paper_pages", ["paper_id"])

    # ------------------------------------------------------------------
    # 4. extracted_data — 结构化摘要
    # ------------------------------------------------------------------
    op.create_table(
        "extracted_data",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=False),
        sa.Column("background", sa.Text(), nullable=True),
        sa.Column("methods", sa.Text(), nullable=True),
        sa.Column("key_results", sa.JSON(), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("translation", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE", name="fk_extracted_data_paper_id"),
        sa.PrimaryKeyConstraint("id", name="pk_extracted_data"),
        sa.UniqueConstraint("paper_id", name="uq_extracted_data_paper_id"),
    )

    # ------------------------------------------------------------------
    # 5. paper_blocks — 论文撰写分块
    # ------------------------------------------------------------------
    op.create_table(
        "paper_blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("block_name", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.CheckConstraint(
            "block_name IN ('abstract', 'introduction', 'methods', 'results', 'discussion')",
            name="ck_paper_blocks_block_name",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paper_blocks"),
        sa.UniqueConstraint("block_name", name="uq_paper_blocks_block_name"),
    )

    # ------------------------------------------------------------------
    # 6. paper_tags — 标签关联表
    # ------------------------------------------------------------------
    op.create_table(
        "paper_tags",
        sa.Column("paper_id", sa.String(length=36), nullable=False),
        sa.Column("tag", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE", name="fk_paper_tags_paper_id"),
        sa.PrimaryKeyConstraint("paper_id", "tag", name="pk_paper_tags"),
    )
    op.create_index("ix_paper_tags_tag", "paper_tags", ["tag"])

    # ------------------------------------------------------------------
    # 7. chat_sessions — 对话会话
    # ------------------------------------------------------------------
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_type", sa.String(length=30), nullable=False),
        sa.Column("paper_ids", sa.JSON(), nullable=True),
        sa.Column("primary_paper_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("messages", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.CheckConstraint(
            "session_type IN ('literature_multi', 'literature_single', 'paper_polish')",
            name="ck_chat_sessions_session_type",
        ),
        sa.ForeignKeyConstraint(["primary_paper_id"], ["papers.id"], ondelete="SET NULL", name="fk_chat_sessions_primary_paper_id"),
        sa.PrimaryKeyConstraint("id", name="pk_chat_sessions"),
    )
    op.create_index("ix_chat_sessions_primary_paper_id", "chat_sessions", ["primary_paper_id"])

    # ------------------------------------------------------------------
    # 8. paper_audit_logs — 调试日志
    # ------------------------------------------------------------------
    op.create_table(
        "paper_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE", name="fk_paper_audit_logs_paper_id"),
        sa.PrimaryKeyConstraint("id", name="pk_paper_audit_logs"),
    )

    # ------------------------------------------------------------------
    # 9. settings — 应用配置（id 固定为 1）
    # ------------------------------------------------------------------
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("api_key_encrypted", sa.BLOB(), nullable=True),
        sa.Column("default_model", sa.String(length=100), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("theme", sa.String(length=20), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.CheckConstraint("id = 1", name="ck_settings_id"),
        sa.PrimaryKeyConstraint("id", name="pk_settings"),
    )

    # ------------------------------------------------------------------
    # 10. FTS5 虚拟表 papers_fts
    # ------------------------------------------------------------------
    # 内部存储 7 个可搜索字段（title, authors, journal, keywords, background,
    # methods, conclusion）。省略 content='papers' 是因为这些字段横跨 papers
    # 与 extracted_data 两张表，外部内容表无法跨表 JOIN；通过触发器显式维护
    # 全部 7 个字段的同步。
    op.execute(
        """
        CREATE VIRTUAL TABLE papers_fts USING fts5(
            title,
            authors,
            journal,
            keywords,
            background,
            methods,
            conclusion
        )
        """
    )

    # ------------------------------------------------------------------
    # 11. FTS5 同步触发器
    # ------------------------------------------------------------------
    # papers 表触发器：维护 title / authors / journal 三列
    op.execute(
        """
        CREATE TRIGGER papers_ai AFTER INSERT ON papers
        BEGIN
            INSERT INTO papers_fts(rowid, title, authors, journal, keywords, background, methods, conclusion)
            VALUES (new.rowid, COALESCE(new.title, ''), COALESCE(new.authors, ''),
                    COALESCE(new.journal, ''), '', '', '', '');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER papers_au AFTER UPDATE ON papers
        BEGIN
            UPDATE papers_fts
            SET title = COALESCE(new.title, ''),
                authors = COALESCE(new.authors, ''),
                journal = COALESCE(new.journal, '')
            WHERE rowid = old.rowid;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER papers_ad AFTER DELETE ON papers
        BEGIN
            DELETE FROM papers_fts WHERE rowid = old.rowid;
        END
        """
    )

    # extracted_data 表触发器：维护 keywords / background / methods / conclusion 四列
    # 注意：papers_fts 的 rowid 是 INTEGER（papers 表的隐式 ROWID），与
    # extracted_data.paper_id (String UUID) 不同；触发器内通过子查询取对应 rowid。
    op.execute(
        """
        CREATE TRIGGER extracted_data_ai AFTER INSERT ON extracted_data
        BEGIN
            UPDATE papers_fts
            SET keywords = COALESCE(new.keywords, ''),
                background = COALESCE(new.background, ''),
                methods = COALESCE(new.methods, ''),
                conclusion = COALESCE(new.conclusion, '')
            WHERE rowid = (SELECT rowid FROM papers WHERE id = new.paper_id);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER extracted_data_au AFTER UPDATE ON extracted_data
        BEGIN
            UPDATE papers_fts
            SET keywords = COALESCE(new.keywords, ''),
                background = COALESCE(new.background, ''),
                methods = COALESCE(new.methods, ''),
                conclusion = COALESCE(new.conclusion, '')
            WHERE rowid = (SELECT rowid FROM papers WHERE id = new.paper_id);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER extracted_data_ad AFTER DELETE ON extracted_data
        BEGIN
            UPDATE papers_fts
            SET keywords = '', background = '', methods = '', conclusion = ''
            WHERE rowid = (SELECT rowid FROM papers WHERE id = old.paper_id);
        END
        """
    )


def downgrade() -> None:
    """回退到空 schema."""
    # 删除顺序：先删触发器与虚拟表（依赖 papers），再删依赖表，最后删主表
    # 触发器与 FTS 只能用 raw SQL（无 Alembic 抽象）
    op.execute("DROP TRIGGER IF EXISTS papers_ai")
    op.execute("DROP TRIGGER IF EXISTS papers_au")
    op.execute("DROP TRIGGER IF EXISTS papers_ad")
    op.execute("DROP TRIGGER IF EXISTS extracted_data_ai")
    op.execute("DROP TRIGGER IF EXISTS extracted_data_au")
    op.execute("DROP TRIGGER IF EXISTS extracted_data_ad")
    op.execute("DROP TABLE IF EXISTS papers_fts")

    # 依赖 papers 的表
    op.drop_table("paper_audit_logs")
    op.drop_table("chat_sessions")
    op.drop_table("paper_tags")
    op.drop_table("extracted_data")
    op.drop_table("paper_pages")

    # 主表
    op.drop_table("papers")

    # 独立表
    op.drop_table("settings")
    op.drop_table("paper_blocks")
    op.drop_table("batches")








