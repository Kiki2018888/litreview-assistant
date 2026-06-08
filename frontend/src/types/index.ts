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
  batch_id: string | null
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
  batch_id: string | null
  created_at: string
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
// Batch (batches 表)
// ---------------------------------------------------------------------------

/** BatchResponse — 批次响应 */
export interface Batch {
  id: string
  name: string
  description: string | null
  paper_count: number
  created_at: string
  updated_at: string
}

/** BatchCreate — 创建批次请求 */
export interface BatchCreateRequest {
  name: string
  description?: string | null
}

/** BatchUpdate — 更新批次请求 */
export interface BatchUpdateRequest {
  name?: string | null
  description?: string | null
}

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
export interface Settings {
  id: number
  has_api_key: boolean
  api_key_preview: string
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
  default_model?: string | null
  temperature?: number | null
  max_tokens?: number | null
  theme?: string | null
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

/** BatchListResponse — 批次分页列表 */
export type BatchListResponse = ListResponse<Batch>

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
  batch_id?: string
  session_id?: string
}

/** 单篇精读问答请求 */
export interface SingleChatRequest {
  question: string
  session_id?: string
  use_fulltext?: boolean
}

/** 批量提取请求 */
export interface BatchExtractRequest {
  batch_id?: string | null
}
