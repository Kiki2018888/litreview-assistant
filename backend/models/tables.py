"""SQLAlchemy 2.0 声明式表定义.

字段名、类型、约束、索引、外键关系严格遵循 SPEC §5.1。
- UUID 使用 String(36) 存储（SQLite 友好）
- 枚举使用 Python Enum + String 列 + CheckConstraint（SQLite 无原生枚举）
- JSON 字段使用 SQLAlchemy JSON 类型
- 外键设置 ON DELETE CASCADE
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BLOB,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类."""


def _uuid4() -> str:
    """生成 UUID v4 字符串."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# 枚举（SQLite 无原生 ENUM，使用 String + CheckConstraint 约束取值）
# ---------------------------------------------------------------------------


class PaperStatus(str, Enum):
    """文献处理状态."""

    PENDING = "pending"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    EXTRACT_FAILED = "extract_failed"


class SessionType(str, Enum):
    """会话类型."""

    LITERATURE_MULTI = "literature_multi"
    LITERATURE_SINGLE = "literature_single"
    PAPER_POLISH = "paper_polish"


class BlockName(str, Enum):
    """论文撰写分块名称（MVP 单用户单论文）."""

    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"


class ClaimForm(str, Enum):
    """论断形态."""
    EFFECT = "effect"
    STATE = "state"
    CHARACTERIZATION = "characterization"
    COMPARISON = "comparison"


class Topic(str, Enum):
    """论断主题."""
    EFFICACY = "efficacy"
    SAFETY = "safety"
    MANUFACTURING = "manufacturing"
    MECHANISM = "mechanism"
    OTHER = "other"


class Direction(str, Enum):
    """效应方向（仅 claim_form=effect 时应有值，条件必填由 Pydantic 校验）."""
    UP = "up"
    DOWN = "down"
    NONE = "none"


class ComparisonResult(str, Enum):
    """比较结果（仅 claim_form=comparison 时应有值，条件必填由 Pydantic 校验）."""
    SIMILAR = "similar"
    SUPERIOR = "superior"
    INFERIOR = "inferior"


class ExtractionSource(str, Enum):
    """提取来源."""
    MODEL = "model"
    HUMAN_VERIFIED = "human_verified"


# ---------------------------------------------------------------------------
# 1. papers — 文献元数据
# ---------------------------------------------------------------------------


class Paper(Base):
    """文献元数据主表."""

    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'extracting', 'completed', 'failed', 'extract_failed')",
            name="ck_papers_status",
        ),
        Index("ix_papers_title", "title"),
        Index("ix_papers_year", "year"),
        Index("ix_papers_status", "status"),
        Index("ix_papers_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    authors: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    journal: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PaperStatus.PENDING.value,
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_scanned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    extraction_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 2. paper_pages — 按页原文
# ---------------------------------------------------------------------------


class PaperPage(Base):
    """按页原文，删除文献时级联删除."""

    __tablename__ = "paper_pages"
    __table_args__ = (
        Index("ix_paper_pages_paper_id", "paper_id"),
        UniqueConstraint("paper_id", "page_number", name="uq_paper_pages_paper_page"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    char_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# 3. extracted_data — 结构化摘要
# ---------------------------------------------------------------------------


class ExtractedData(Base):
    """结构化摘要（一篇文献一份）."""

    __tablename__ = "extracted_data"
    __table_args__ = (
        UniqueConstraint("paper_id", name="uq_extracted_data_paper_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    research_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sample_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sample_size: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_methods: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    key_data: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    limitations: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    background: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methods: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_results: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    conclusion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    keywords: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    raw_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    translation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# 4. paper_blocks — 论文撰写分块
# ---------------------------------------------------------------------------


class PaperBlock(Base):
    """论文撰写分块（MVP 单用户单论文，block_name 唯一）."""

    __tablename__ = "paper_blocks"
    __table_args__ = (
        CheckConstraint(
            "block_name IN ('abstract', 'introduction', 'methods', 'results', 'discussion')",
            name="ck_paper_blocks_block_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    block_name: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 5. projects — 科研项目（原 batches）
# ---------------------------------------------------------------------------


class Project(Base):
    """科研项目分组."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


# 向后兼容别名（逐步移除）
Batch = Project


# ---------------------------------------------------------------------------
# 6. paper_tags — 标签关联表（联合主键）
# ---------------------------------------------------------------------------


class PaperTag(Base):
    """标签关联表，paper_id + tag 联合主键."""

    __tablename__ = "paper_tags"
    __table_args__ = (
        Index("ix_paper_tags_tag", "tag"),
    )

    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag: Mapped[str] = mapped_column(String(50), primary_key=True)


# ---------------------------------------------------------------------------
# 7. chat_sessions — 对话会话
# ---------------------------------------------------------------------------


class ChatSession(Base):
    """对话会话（跨文献/单篇/润色）."""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint(
            "session_type IN ('literature_multi', 'literature_single', 'paper_polish')",
            name="ck_chat_sessions_session_type",
        ),
        Index("ix_chat_sessions_primary_paper_id", "primary_paper_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    session_type: Mapped[str] = mapped_column(String(30), nullable=False)
    paper_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    primary_paper_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    messages: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 8. paper_audit_logs — 调试日志（可选）
# ---------------------------------------------------------------------------


class PaperAuditLog(Base):
    """调试日志，paper_id 可空（全局事件也能记录）."""

    __tablename__ = "paper_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    paper_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 9. settings — 应用配置（单行，id 固定为 1）
# ---------------------------------------------------------------------------


class Setting(Base):
    """应用配置（API Key / 模型 / 主题等）."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_settings_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    api_key_encrypted: Mapped[Optional[bytes]] = mapped_column(BLOB, nullable=True)
    api_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="auto", server_default="auto"
    )
    api_base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    default_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    theme: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 10. claims — 原子论断
# ---------------------------------------------------------------------------


class Claim(Base):
    """原子论断表（机会信号地基：局限聚类/矛盾检测/方法迁移）."""

    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(
            "claim_form IN ('effect', 'state', 'characterization', 'comparison')",
            name="ck_claims_claim_form",
        ),
        CheckConstraint(
            "topic IS NULL OR topic IN ('efficacy', 'safety', 'manufacturing', 'mechanism', 'other')",
            name="ck_claims_topic",
        ),
        CheckConstraint(
            "extraction_source IN ('model', 'human_verified')",
            name="ck_claims_extraction_source",
        ),
        Index("ix_claims_paper_id", "paper_id"),
        Index("ix_claims_claim_form", "claim_form"),
        Index("ix_claims_topic", "topic"),
        Index("ix_claims_is_limitation", "is_limitation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_form: Mapped[str] = mapped_column(String(20), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    comparison_result: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    magnitude: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    stat_support: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_limitation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quote: Mapped[str] = mapped_column(String(300), nullable=False)
    quote_page: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExtractionSource.MODEL.value,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


__all__ = [
    "Base",
    "Paper",
    "PaperPage",
    "ExtractedData",
    "PaperBlock",
    "Project",
    "Batch",
    "PaperTag",
    "ChatSession",
    "PaperAuditLog",
    "Setting",
    "Claim",
    "PaperStatus",
    "SessionType",
    "BlockName",
    "ClaimForm",
    "Topic",
    "Direction",
    "ComparisonResult",
    "ExtractionSource",
]
