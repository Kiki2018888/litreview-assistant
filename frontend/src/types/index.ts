// ============================================================================
// ResearchAssistant 前端类型定义
// 来源：backend/models/schemas.py 的 Pydantic Schema
// 策略：Response Schema → TypeScript interface（字段名/类型严格对应）
// ============================================================================

// ---------------------------------------------------------------------------
// 枚举
// ---------------------------------------------------------------------------

/** 文献处理状态 */
export type PaperStatus =
  | 'pending'
  | 'extracting'
  | 'completed'
  | 'failed'
  | 'extract_failed'

/** 会话类型 */
export type SessionType =
  | 'literature_multi'
  | 'literature_single'
  | 'paper_polish'

/** 论文撰写分块名称 */
export type BlockName =
  | 'abstract'
  | 'introduction'
  | 'methods'
  | 'results'
  | 'discussion'

// ---------------------------------------------------------------------------
// Paper (papers 表)
// ---------------------------------------------------------------------------

/** PaperResponse — 文献基础响应 */
export interface Paper {
  id: string
  file_path: string
  file_size: number | null
  page_count: number | null
  title: string | null
  authors: string[] | null
  year: number | null
  journal: string | null
  doi: string | null
  status: PaperStatus
  project_id: string | null
  is_scanned: boolean
  extraction_attempts: number
  last_error: string | null
  created_at: string
  extracted_at: string | null
  updated_at: string
}

/** PaperListItem — 文献列表项（轻量，不含 pages 与 extracted_data） */
export interface PaperListItem {
  id: string
  title: string | null
  authors: string[] | null
  year: number | null
  journal: string | null
  status: PaperStatus
  tags: string[]
  project_id: string | null
  project_name: string | null
  created_at: string
  claims_count: number
}

/** ClaimItem — 单条 claim（文献库详情/列表查看用） */
export interface ClaimItem {
  id: string
  claim_form: string
  subject: string | null
  topic: string | null
  direction: string | null
  comparison_result: string | null
  magnitude: string | null
  stat_support: boolean
  is_limitation: boolean
  quote: string
  quote_page: number
  quote_status: string | null
  notes: string | null
}

/** ClaimsListResponse — claims 列表响应 */
export interface ClaimsListResponse {
  project_id: string
  paper_id: string | null
  total: number
  claims: ClaimItem[]
}

/** PaperDetailResponse — 文献详情（含 tags 与 extracted_data） */
export interface PaperDetail extends Paper {
  tags: string[]
  extracted_data: ExtractedData | null
}

/** PaperUploadResult — 单文件上传结果 */
export interface PaperUploadResult {
  id: string
  title: string | null
  status: PaperStatus
  page_count: number | null
}

/** PaperUploadResponse — 批量上传响应 */
export interface PaperUploadResponse {
  uploaded: PaperUploadResult[]
}

// ---------------------------------------------------------------------------
// PaperPage (paper_pages 表)
// ---------------------------------------------------------------------------

/** PageTextResponse — 单页文本响应 */
export interface PageText {
  page_number: number
  text_content: string | null
  char_count: number | null
}

// ---------------------------------------------------------------------------
// ExtractedData (extracted_data 表)
// ---------------------------------------------------------------------------

/** ExtractedDataResponse — AI 提取的结构化数据 */
export interface ExtractedData {
  id: string
  paper_id: string
  background: string | null
  methods: string | null
  key_results: string[] | null
  conclusion: string | null
  keywords: string[] | null
  raw_json: Record<string, unknown> | null
  translation: string | null
  extracted_at: string | null
}

// ---------------------------------------------------------------------------
// Project (projects 表，原 batches)
// ---------------------------------------------------------------------------

/** ProjectResponse — 项目响应 */
export interface Project {
  id: string
  name: string
  description: string | null
  paper_count: number
  is_default: boolean
  created_at: string
  updated_at: string
}

/** ProjectDetailResponse — 项目详情（含文献 ID 列表） */
export interface ProjectDetail extends Project {
  paper_ids: string[]
}

/** ProjectCreate — 创建项目请求 */
export interface ProjectCreateRequest {
  name: string
  description?: string | null
}

/** ProjectUpdate — 更新项目请求 */
export interface ProjectUpdateRequest {
  name?: string | null
  description?: string | null
}

/** ProjectDeleteResponse — 删除项目响应 */
export interface ProjectDeleteResponse {
  success: boolean
  moved_count: number
}

/** 向后兼容别名（逐步移除） */
export type Batch = Project
export type BatchCreateRequest = ProjectCreateRequest
export type BatchUpdateRequest = ProjectUpdateRequest

// ---------------------------------------------------------------------------
// ChatSession (chat_sessions 表)
// ---------------------------------------------------------------------------

/** ChatMessage — OpenAI 消息格式 */
export interface ChatMessage {
  role: string
  content: string
}

/** ChatSessionResponse — 会话响应 */
export interface ChatSession {
  id: string
  session_type: SessionType
  paper_ids: string[] | null
  primary_paper_id: string | null
  title: string | null
  messages: ChatMessage[] | null
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Settings (settings 表)
// ---------------------------------------------------------------------------

/** SettingResponse — 设置响应（api_key 不返回明文） */
export type ApiProvider =
  | "auto"
  | "moonshot"
  | "kimi-coding"
  | "deepseek"
  | "custom"

export interface Settings {
  id: number
  has_api_key: boolean
  api_key_preview: string
  api_provider: ApiProvider
  api_base_url: string
  default_model: string | null
  available_models: string[]
  temperature: number | null
  max_tokens: number | null
  theme: string | null
  updated_at: string
}

/** SettingUpdate — 设置更新请求 */
export interface SettingsUpdateRequest {
  api_key?: string | null
  api_provider?: ApiProvider | null
  api_base_url?: string | null
  default_model?: string | null
  temperature?: number | null
  max_tokens?: number | null
  theme?: string | null
}

/** ApiKeyTestResponse — API Key 测试响应 */
export interface ApiKeyTestResponse {
  valid: boolean
  message: string
  provider?: string | null
  base_url?: string | null
}

// ---------------------------------------------------------------------------
// Tag (paper_tags 表)
// ---------------------------------------------------------------------------

/** TagSummaryItem — 单个标签汇总 */
export interface TagSummaryItem {
  tag: string
  count: number
}

/** TagSummaryResponse — 标签汇总响应 */
export interface TagSummaryResponse {
  tags: TagSummaryItem[]
}

/** PaperTagsUpdateRequest — 批量更新文献标签请求 */
export interface PaperTagsUpdateRequest {
  tags: string[]
}

/** PaperTagsUpdateResponse — 批量更新文献标签响应 */
export interface PaperTagsUpdateResponse {
  id: string
  tags: string[]
}

// ---------------------------------------------------------------------------
// 通用列表响应包装
// ---------------------------------------------------------------------------

/** ListResponse — 分页列表通用响应 */
export interface ListResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** PaperListResponse — 文献分页列表 */
export type PaperListResponse = ListResponse<PaperListItem>

/** ProjectListResponse — 项目分页列表 */
export type ProjectListResponse = ListResponse<Project>

/** @deprecated 使用 ProjectListResponse */
export type BatchListResponse = ProjectListResponse

/** ChatSessionListResponse — 会话分页列表 */
export type ChatSessionListResponse = ListResponse<ChatSession>

// ---------------------------------------------------------------------------
// 统计
// ---------------------------------------------------------------------------

/** PaperStatsResponse — 文献统计响应 */
export interface PaperStats {
  total: number
  pending: number
  extracting: number
  completed: number
  failed: number
  extract_failed: number
}

// ---------------------------------------------------------------------------
// SSE 事件类型
// ---------------------------------------------------------------------------

/** 通用 SSE 事件 */
export interface SSEEvent {
  type: string
  [key: string]: unknown
}

// ── 聊天 SSE ──

/** 聊天 chunk 事件 */
export interface ChatChunkEvent extends SSEEvent {
  type: 'chunk'
  content: string
}

/** 聊天 result 事件 */
export interface ChatResultEvent extends SSEEvent {
  type: 'result'
  session_id: string
  answer_length: number
}

/** 聊天 error 事件 */
export interface ChatErrorEvent extends SSEEvent {
  type: 'error'
  code: string
  message: string
}

/** 聊天 done 事件 */
export interface ChatDoneEvent extends SSEEvent {
  type: 'done'
}

// ── 单篇提取 SSE ──

/** 提取 status 事件 */
export interface ExtractStatusEvent extends SSEEvent {
  type: 'status'
  status: 'extracting'
  attempt: number
  max_retries: number
}

/** 提取 chunk 事件（含完整 JSON 响应） */
export interface ExtractChunkEvent extends SSEEvent {
  type: 'chunk'
  content: string
}

/** 提取 retry 事件 */
export interface ExtractRetryEvent extends SSEEvent {
  type: 'retry'
  attempt: number
  max_retries: number
  delay: number
}

/** 提取 result 事件 */
export interface ExtractResultEvent extends SSEEvent {
  type: 'result'
  paper_id: string
  title: string
  keywords: string[]
}

/** 提取 error 事件 */
export interface ExtractErrorEvent extends SSEEvent {
  type: 'error'
  code: string
  message: string
  attempt?: number
}

/** 提取 cancelled 事件 */
export interface ExtractCancelledEvent extends SSEEvent {
  type: 'cancelled'
  message: string
}

/** 提取 done 事件 */
export interface ExtractDoneEvent extends SSEEvent {
  type: 'done'
}

// ── 批量提取 SSE ──

/** 批量提取 progress 事件 */
export interface BatchProgressEvent extends SSEEvent {
  type: 'progress'
  current: number
  total: number
  paper_id: string
  status: 'extracting' | 'completed' | 'failed'
  title: string
  error?: string
}

/** 批量提取 done 事件 */
export interface BatchDoneEvent extends SSEEvent {
  type: 'done'
  success_count: number
  fail_count: number
  message?: string
}

// ---------------------------------------------------------------------------
// 请求体类型
// ---------------------------------------------------------------------------

/** 跨文献问答请求 */
export interface ChatRequest {
  question: string
  paper_ids?: string[]
  project_id?: string
  session_id?: string
}

/** 单篇精读问答请求 */
export interface SingleChatRequest {
  question: string
  session_id?: string
  use_fulltext?: boolean
}

/** 批量删除文献请求 */
export interface BatchDeleteRequest {
  paper_ids: string[]
}

/** 批量删除文献响应 */
export interface BatchDeleteResponse {
  success: boolean
  deleted_count: number
}

/** 项目批量提取请求（路径参数指定 project_id，通常无需 body） */
export interface ProjectExtractRequest {
  project_id?: string | null
}

/** @deprecated 使用 ProjectExtractRequest */
export type BatchExtractRequest = ProjectExtractRequest

// ---------------------------------------------------------------------------
// Adjudication — 裁决（ADR-7）
// ---------------------------------------------------------------------------

/** 裁决状态 */
export type AdjudicationStatus = "pending" | "accepted" | "rejected"
/** claim 被加入信号的方式 */
export type ClaimAddition = "adopted_from_group" | "manual_remove"

/** 候选组列表项 */
export interface CandidateGroup {
  id: string
  run_id: string
  group_label: string
  topic: string | null
  grouping_method: string | null
  grouping_basis: string | null
  cross_paper: boolean
  claim_count: number
  created_at: string
  adjudication_status: string | null
  signal_id: string | null
  signal_name: string | null
}

/** 候选组内一条 claim（候选组详情 & 信号详情共用） */
export interface ClaimInfo {
  claim_id: string
  paper_id: string
  paper_title: string
  quote: string
  quote_page: number | null
  topic: string | null
  context_summary: string | null
  claim_form: string | null
  quote_status: string | null
  /** ADR-7 命脉：研究对象（如 "iPSC-derived RPE cells"） */
  subject: string | null
  added_by?: string
  added_at?: string
}

/** 候选组详情 */
export interface CandidateGroupDetail {
  id: string
  run_id: string
  group_label: string
  topic: string | null
  grouping_method: string | null
  grouping_basis: string | null
  cross_paper: boolean
  claim_count: number
  created_at: string
  claims: ClaimInfo[]
}

/** 信号列表项 / 创建响应 */
export interface Signal {
  id: string
  signal_name: string | null
  status: string
  topic: string | null
  candidate_group_id: string | null
  human_rationale: string | null
  claim_count: number
  created_at: string
  updated_at: string
  adjudicated_at: string | null
}

/** 信号详情（含 claims） */
export interface SignalDetail extends Signal {
  claims: ClaimInfo[]
}

// ---------------------------------------------------------------------------
// Claims 抽取 Job（Step 6）
// ---------------------------------------------------------------------------

/** claims 抽取 Job 创建请求 */
export interface ClaimsExtractStartRequest {
  model?: string | null
  force?: boolean
}

/** claims 抽取 Job 创建响应 */
export interface ClaimsExtractStartResponse {
  job_id: string
  project_id: string
  status: string
  pending_paper_count: number
  model: string
  estimate: Record<string, unknown>
}

/** Job 状态响应 */
export interface JobStatusResponse {
  job_id: string
  project_id: string
  status: string
  total_paper_count: number
  completed_count: number
  failed_count: number
  current_paper_id: string | null
  current_paper_title: string | null
  error_summary: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

/** 耗时预估响应 */
export interface ClaimsEstimateResponse {
  paper_count: number
  estimate: Record<string, unknown>
}

// ── Claims 抽取 SSE 事件 ──

/** claims Job 状态变更事件 */
export interface ClaimsJobStatusEvent extends SSEEvent {
  type: 'job_status'
  job_id: string
  status: string
}

/** claims 单篇进度事件 */
export interface ClaimsPaperProgressEvent extends SSEEvent {
  type: 'paper_progress'
  paper_id: string
  title: string
  index: number
  total: number
  status: 'extracting' | 'completed' | 'failed'
  error?: string
}

/** claims Job 完成事件 */
export interface ClaimsJobDoneEvent extends SSEEvent {
  type: 'job_done'
  job_id: string
  succeeded: number
  failed: number
  total: number
  status: string
  message?: string
}

/** claims 抽取错误事件 */
export interface ClaimsJobErrorEvent extends SSEEvent {
  type: 'error'
  message: string
}
