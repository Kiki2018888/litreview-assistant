"""Pydantic v2 Schema 定义.

前后端共用的数据契约，字段名/类型与 tables.py 严格对应。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.models.tables import BlockName, PaperStatus, SessionType


# ---------------------------------------------------------------------------
# 通用配置
# ---------------------------------------------------------------------------


class _ORMModel(BaseModel):
    """支持 ORM 模型转换的基类."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 1. papers
# ---------------------------------------------------------------------------


class PaperBase(_ORMModel):
    """文献基础字段."""

    file_path: str
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    status: PaperStatus = PaperStatus.PENDING
    project_id: Optional[str] = None
    is_scanned: bool = False
    extraction_attempts: int = 0
    last_error: Optional[str] = None


class PaperCreate(PaperBase):
    """创建文献请求（来自 PDF 上传）."""


class PaperUpdate(_ORMModel):
    """更新文献（部分字段）."""

    file_path: Optional[str] = None
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    status: Optional[PaperStatus] = None
    project_id: Optional[str] = None
    is_scanned: Optional[bool] = None
    extraction_attempts: Optional[int] = None
    last_error: Optional[str] = None
    extracted_at: Optional[datetime] = None


class PaperResponse(PaperBase):
    """文献响应."""

    id: str
    created_at: datetime
    extracted_at: Optional[datetime] = None
    updated_at: datetime


# ---------------------------------------------------------------------------
# 2. paper_pages
# ---------------------------------------------------------------------------


class PaperPageBase(_ORMModel):
    page_number: int
    text_content: Optional[str] = None
    char_count: Optional[int] = None


class PaperPageCreate(PaperPageBase):
    paper_id: str


class PaperPageResponse(PaperPageBase):
    id: str
    paper_id: str


# ---------------------------------------------------------------------------
# 3. extracted_data
# ---------------------------------------------------------------------------


class ExtractedDataBase(_ORMModel):
    background: Optional[str] = None
    methods: Optional[str] = None
    key_results: Optional[list[str]] = None
    conclusion: Optional[str] = None
    keywords: Optional[list[str]] = None
    raw_json: Optional[dict[str, Any]] = None
    translation: Optional[str] = None


class ExtractedDataCreate(ExtractedDataBase):
    paper_id: str


class ExtractedDataUpdate(ExtractedDataBase):
    extracted_at: Optional[datetime] = None


class ExtractedDataResponse(ExtractedDataBase):
    id: str
    paper_id: str
    extracted_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# 4. paper_blocks
# ---------------------------------------------------------------------------


class PaperBlockBase(_ORMModel):
    content: Optional[str] = None


class PaperBlockCreate(PaperBlockBase):
    block_name: BlockName


class PaperBlockUpdate(_ORMModel):
    content: Optional[str] = None


class PaperBlockResponse(PaperBlockBase):
    id: str
    block_name: BlockName
    updated_at: datetime


class PaperBlocksResponse(_ORMModel):
    """论文撰写全部分块响应（block_name → PaperBlockResponse | None）."""

    abstract: Optional[PaperBlockResponse] = None
    introduction: Optional[PaperBlockResponse] = None
    methods: Optional[PaperBlockResponse] = None
    results: Optional[PaperBlockResponse] = None
    discussion: Optional[PaperBlockResponse] = None


# ---------------------------------------------------------------------------
# 5. projects（原 batches）
# ---------------------------------------------------------------------------


class ProjectBase(_ORMModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    paper_count: int = 0


class ProjectCreate(_ORMModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class ProjectUpdate(_ORMModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None


class ProjectResponse(ProjectBase):
    id: str
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class ProjectDetailResponse(ProjectResponse):
    paper_ids: list[str] = Field(default_factory=list)


class MovePapersRequest(_ORMModel):
    paper_ids: list[str] = Field(..., min_length=1)


class MovePapersResponse(_ORMModel):
    success: bool = True
    moved_count: int = 0


class ProjectDeleteResponse(_ORMModel):
    success: bool = True
    moved_count: int = 0


# 向后兼容别名
BatchBase = ProjectBase
BatchCreate = ProjectCreate
BatchUpdate = ProjectUpdate
BatchResponse = ProjectResponse


# ---------------------------------------------------------------------------
# 6. paper_tags
# ---------------------------------------------------------------------------


class PaperTagBase(_ORMModel):
    tag: str = Field(..., max_length=50)


class PaperTagCreate(PaperTagBase):
    paper_id: str


class PaperTagResponse(PaperTagBase):
    paper_id: str


class PaperTagsUpdateRequest(_ORMModel):
    """批量更新文献标签请求."""

    tags: list[str] = Field(default_factory=list)


class PaperTagsUpdateResponse(_ORMModel):
    id: str
    tags: list[str]


class PaperListItem(_ORMModel):
    """文献列表项（轻量，不含 pages 与 extracted_data）."""

    id: str
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    status: PaperStatus
    tags: list[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    created_at: datetime


class PaperDetailResponse(PaperResponse):
    """文献详情（含 tags 与 extracted_data）."""

    tags: list[str] = Field(default_factory=list)
    extracted_data: Optional[ExtractedDataResponse] = None


class PaperUploadResult(_ORMModel):
    """单文件上传结果."""

    id: str
    title: Optional[str] = None
    status: PaperStatus
    page_count: Optional[int] = None


class PaperUploadResponse(_ORMModel):
    """批量上传响应."""

    uploaded: list[PaperUploadResult]


class PaperParseResponse(_ORMModel):
    """手动触发解析响应."""

    paper_id: str
    page_count: Optional[int] = None
    status: PaperStatus


class TagSummaryItem(_ORMModel):
    """单个标签汇总."""

    tag: str
    count: int


class TagSummaryResponse(_ORMModel):
    """标签汇总响应."""

    tags: list[TagSummaryItem]


class ProjectStatsItem(_ORMModel):
    project_id: str
    project_name: str
    count: int


class PaperStatsResponse(_ORMModel):
    """文献统计响应."""

    total: int = 0
    pending: int = 0
    extracting: int = 0
    completed: int = 0
    failed: int = 0
    extract_failed: int = 0
    by_project: list[ProjectStatsItem] = Field(default_factory=list)


class BatchDeleteRequest(_ORMModel):
    paper_ids: list[str] = Field(..., min_length=1)


class BatchDeleteResponse(_ORMModel):
    success: bool = True
    deleted_count: int = 0


class PaperProjectUpdateRequest(_ORMModel):
    project_id: str


class PaperProjectUpdateResponse(_ORMModel):
    id: str
    project_id: str
    project_name: str


class DeleteResponse(_ORMModel):
    """删除响应."""

    success: bool = True


class PageTextResponse(_ORMModel):
    """单页文本响应."""

    page_number: int
    text_content: Optional[str] = None
    char_count: Optional[int] = None


# ---------------------------------------------------------------------------
# 7. chat_sessions
# ---------------------------------------------------------------------------


class ChatMessage(_ORMModel):
    """OpenAI 消息格式."""

    role: str
    content: str


class ChatSessionBase(_ORMModel):
    session_type: SessionType
    paper_ids: Optional[list[str]] = None
    primary_paper_id: Optional[str] = None
    title: Optional[str] = None
    messages: Optional[list[ChatMessage]] = None


class ChatSessionCreate(ChatSessionBase):
    """创建会话请求."""


class ChatSessionUpdate(_ORMModel):
    paper_ids: Optional[list[str]] = None
    primary_paper_id: Optional[str] = None
    title: Optional[str] = None
    messages: Optional[list[ChatMessage]] = None


class ChatSessionResponse(ChatSessionBase):
    id: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# 8. paper_audit_logs
# ---------------------------------------------------------------------------


class PaperAuditLogBase(_ORMModel):
    action: str = Field(..., max_length=50)
    detail: Optional[dict[str, Any]] = None


class PaperAuditLogCreate(PaperAuditLogBase):
    paper_id: Optional[str] = None


class PaperAuditLogResponse(PaperAuditLogBase):
    id: str
    paper_id: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# 9. settings
# ---------------------------------------------------------------------------


class SettingBase(_ORMModel):
    api_provider: Optional[str] = "auto"
    api_base_url: Optional[str] = None
    default_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    theme: Optional[str] = None


class SettingUpdate(_ORMModel):
    """设置更新请求（API Key 不直接进 schema，由服务层处理加密）."""

    api_key: Optional[str] = None
    api_provider: Optional[str] = None
    api_base_url: Optional[str] = None
    default_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    theme: Optional[str] = None


class SettingResponse(SettingBase):
    """设置响应（api_key_encrypted 不直接返回明文）."""

    id: int
    has_api_key: bool = False
    updated_at: datetime


# ---------------------------------------------------------------------------
# 通用列表响应包装
# ---------------------------------------------------------------------------


class ListResponse(_ORMModel):
    """分页列表通用响应."""

    items: list[Any]
    total: int
    page: int
    page_size: int


__all__ = [
    # 1. papers
    "PaperBase",
    "PaperCreate",
    "PaperUpdate",
    "PaperResponse",
    # 2. paper_pages
    "PaperPageBase",
    "PaperPageCreate",
    "PaperPageResponse",
    # 3. extracted_data
    "ExtractedDataBase",
    "ExtractedDataCreate",
    "ExtractedDataUpdate",
    "ExtractedDataResponse",
    # 4. paper_blocks
    "PaperBlockBase",
    "PaperBlockCreate",
    "PaperBlockUpdate",
    "PaperBlockResponse",
    "PaperBlocksResponse",
    # 5. batches
    "BatchBase",
    "BatchCreate",
    "BatchUpdate",
    "BatchResponse",
    # 6. paper_tags
    "PaperTagBase",
    "PaperTagCreate",
    "PaperTagResponse",
    "PaperTagsUpdateRequest",
    "PaperTagsUpdateResponse",
    "PaperListItem",
    "PaperDetailResponse",
    "PaperUploadResult",
    "PaperUploadResponse",
    "PaperParseResponse",
    "TagSummaryItem",
    "TagSummaryResponse",
    "PaperStatsResponse",
    "DeleteResponse",
    "PageTextResponse",
    # 7. chat_sessions
    "ChatMessage",
    "ChatSessionBase",
    "ChatSessionCreate",
    "ChatSessionUpdate",
    "ChatSessionResponse",
    # 8. paper_audit_logs
    "PaperAuditLogBase",
    "PaperAuditLogCreate",
    "PaperAuditLogResponse",
    # 9. settings
    "SettingBase",
    "SettingUpdate",
    "SettingResponse",
    # 通用
    "ListResponse",
]
