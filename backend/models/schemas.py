"""Pydantic v2 Schema 定义.

前后端共用的数据契约，字段名/类型与 tables.py 严格对应。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.tables import BlockName, PaperStatus, SessionType, SignalStatus, ClaimAddition


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
    research_question: Optional[str] = None
    sample_source: Optional[str] = None
    sample_size: Optional[str] = None
    key_methods: Optional[list[str]] = None
    key_data: Optional[list[str]] = None
    limitations: Optional[list[str]] = None
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
# 3a. ExtractedDataContract — 提取质量校验 Schema（ADR-2）
# ---------------------------------------------------------------------------

# 数值正则：容忍数字/百分比/p值/倍数/中文数字
_NUMERIC_RE = re.compile(
    r"(?x)"
    r"\d[\d,.]*(?:e[+-]?\d+)?"   # 数字（小数、千分位、科学计数法）
    r"|"
    r"[零一二三四五六七八九十百千万亿]+"  # 中文数字
    r"|"
    r"p\s*[<≤>=≈]\s*0?\.\d+"     # p值
    r"|"
    r"[%％倍]"                     # 百分比/单位/倍数后缀
)


class ExtractedDataContract(BaseModel):
    """提取质量契约 Schema（ADR-2）.

    用于校验 API 返回的 JSON 是否满足最低质量要求。
    与 ExtractedData 表字段对应，但不要求 ORM 兼容。
    """

    model_config = ConfigDict(extra="allow")

    title: str = Field(default="")
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    research_question: str = Field(..., min_length=1)
    sample_source: str = Field(..., min_length=1)
    sample_size: Optional[str] = ""
    key_methods: list[str] = Field(default_factory=list)
    key_data: list[str] = Field(..., min_length=1)
    conclusion: str = Field(..., min_length=1)
    limitations: list[str] = Field(..., min_length=1)
    keywords: list[str] = Field(default_factory=list)
    # 兼容旧字段
    background: Optional[str] = ""
    methods: Optional[str] = ""
    key_results: list[str] = Field(default_factory=list)

    @field_validator("key_data")
    @classmethod
    def _key_data_has_numeric(cls, v: list[str]) -> list[str]:
        """key_data 至少 1 条，且每条含具体数值."""
        if len(v) < 1:
            raise ValueError("key_data 至少需要 1 条核心数据")
        for i, item in enumerate(v):
            if not _NUMERIC_RE.search(item):
                raise ValueError(
                    f"key_data[{i}] 缺少具体数值/指标: '{item}'。"
                    "禁止'显著增加'等模糊表述，请补充具体数字。"
                )
        return v

    @field_validator("limitations")
    @classmethod
    def _limitations_at_least_one(cls, v: list[str]) -> list[str]:
        """limitations 至少 1 条."""
        if len(v) < 1:
            raise ValueError("limitations 至少需要 1 条研究局限性")
        return v


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
# 10. adjudication — 裁决（ADR-7：AI召回候选组，人裁决信号）
# ---------------------------------------------------------------------------


class AdjudicateRequest(_ORMModel):
    """创建裁决请求（采纳或否决一个候选组）."""

    action: str = Field(..., pattern=r"^(accept|reject)$")
    candidate_group_id: str
    signal_name: Optional[str] = Field(default=None, max_length=200)
    human_rationale: Optional[str] = None


class SignalUpdateRequest(_ORMModel):
    """修改已有裁决."""

    signal_name: Optional[str] = Field(default=None, max_length=200)
    status: Optional[SignalStatus] = None
    human_rationale: Optional[str] = None


class SignalClaimResponse(_ORMModel):
    """信号中的一条 claim."""

    claim_id: str
    paper_id: str
    paper_title: Optional[str] = None
    quote: str
    quote_page: int
    topic: Optional[str] = None
    context_summary: Optional[str] = None
    claim_form: Optional[str] = None       # F-05: 对齐 get_signal_detail 实际返回
    quote_status: Optional[str] = None     # F-05: verified/unverified/null
    added_by: str
    added_at: datetime


class SignalResponse(_ORMModel):
    """信号响应."""

    id: str
    signal_name: Optional[str] = None
    status: str
    topic: Optional[str] = None
    candidate_group_id: Optional[str] = None
    human_rationale: Optional[str] = None
    claim_count: int
    created_at: datetime
    updated_at: datetime
    adjudicated_at: Optional[datetime] = None


class SignalDetailResponse(SignalResponse):
    """信号详情（含 claims 列表）."""

    claims: list[SignalClaimResponse] = Field(default_factory=list)


class CandidateGroupResponse(_ORMModel):
    """候选组响应（含裁决状态）."""

    id: str
    run_id: str
    group_label: str
    topic: str
    grouping_method: str
    grouping_basis: Optional[str] = None
    cross_paper: bool
    claim_count: int
    created_at: datetime
    # 关联的裁决状态（直接查询 signals 表计算）
    adjudication_status: Optional[str] = None  # null=pending, 或 accepted/rejected
    signal_id: Optional[str] = None
    signal_name: Optional[str] = None


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
    "ExtractedDataContract",
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
    # 10. adjudication
    "AdjudicateRequest",
    "SignalUpdateRequest",
    "SignalClaimResponse",
    "SignalResponse",
    "SignalDetailResponse",
    "CandidateGroupResponse",
    # 通用
    "ListResponse",
]
