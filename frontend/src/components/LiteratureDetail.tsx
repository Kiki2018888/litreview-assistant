import { useState, useEffect, useCallback, useRef } from "react"
import {
  X,
  Loader2,
  RefreshCw,
  FileSearch,
  Trash2,
  Languages,
  Pencil,
  Check,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  MessageSquare,
} from "lucide-react"
import { toast } from "sonner"
import { cn } from "../lib/utils"
import { apiGet, apiPost, apiPut, apiDelete, resolveApiBase } from "../api/client"

import PdfViewer from "./PdfViewer"
import type { PaperDetail, PaperStatus, ExtractedData } from "../types"

// ============================================================================
// 常量
// ============================================================================

const STATUS_MAP: Record<PaperStatus, { label: string; className: string }> = {
  pending: { label: "待处理", className: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400" },
  extracting: { label: "提取中", className: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400" },
  completed: { label: "已完成", className: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" },
  failed: { label: "失败", className: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400" },
  extract_failed: { label: "提取失败", className: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400" },
}

// SSE 提取事件类型
interface ExtractEvent {
  type: "status" | "chunk" | "retry" | "result" | "error" | "cancelled" | "done"
  status?: string
  attempt?: number
  max_retries?: number
  delay?: number
  content?: string
  paper_id?: string
  title?: string
  keywords?: string[]
  code?: string
  message?: string
}

// ============================================================================
// Props
// ============================================================================

interface LiteratureDetailProps {
  paperId: string | null
  onClose: () => void
  /** 操作后刷新外部列表（如删除、提取完成） */
  onRefresh?: () => void
  /** 打开精读对话面板 */
  onOpenChat?: (paperId: string) => void
}

// ============================================================================
// LiteratureDetail 组件
// ============================================================================

export default function LiteratureDetail({ paperId, onClose, onRefresh, onOpenChat }: LiteratureDetailProps) {
  // ── 数据状态 ──
  const [paper, setPaper] = useState<PaperDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── 操作状态 ──
  const [parsing, setParsing] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [translating, setTranslating] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [translatingResult, setTranslatingResult] = useState<string | null>(null)

  // ── 提取进度 ──
  const [extractProgress, setExtractProgress] = useState<string>("")
  const [extractAttempt, setExtractAttempt] = useState(0)
  const [extractMaxRetries, setExtractMaxRetries] = useState(0)

  // ── 标签编辑 ──
  const [editingTags, setEditingTags] = useState(false)
  const [tagInput, setTagInput] = useState("")
  const [savingTags, setSavingTags] = useState(false)

  // ── 折叠面板 ──
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["summary", "metadata"])
  )

  // AbortController for SSE
  const extractAbortRef = useRef<AbortController | null>(null)

  // ── 获取文献详情 ──

  const fetchDetail = useCallback(async () => {
    if (!paperId) return
    setLoading(true)
    setError(null)
    setTranslatingResult(null)

    try {
      const data = await apiGet<PaperDetail>(`/literature/${paperId}`)
      setPaper(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载文献详情失败")
      setPaper(null)
    } finally {
      setLoading(false)
    }
  }, [paperId])

  useEffect(() => {
    fetchDetail()
    return () => {
      extractAbortRef.current?.abort()
    }
  }, [fetchDetail])

  // ── 操作：重新解析 ──

  const handleReparse = useCallback(async () => {
    if (!paperId || parsing) return
    setParsing(true)
    try {
      await apiPost(`/literature/${paperId}/parse`)
      toast.success("已触发重新解析")
      await fetchDetail()
      onRefresh?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "重新解析失败")
    } finally {
      setParsing(false)
    }
  }, [paperId, parsing, fetchDetail, onRefresh])

  // ── 操作：提取摘要（SSE） ──

  const handleExtract = useCallback(async () => {
    if (!paperId || extracting) return

    extractAbortRef.current?.abort()
    extractAbortRef.current = new AbortController()

    setExtracting(true)
    setExtractProgress("正在连接…")
    setExtractAttempt(0)
    setExtractMaxRetries(0)

    try {
      const base = await resolveApiBase()
      const res = await fetch(`${base}/literature/${paperId}/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: extractAbortRef.current.signal,
      })

      if (!res.ok) {
        throw new Error(`提取请求失败: ${res.status}`)
      }

      const reader = res.body?.getReader()
      if (!reader) throw new Error("无法读取SSE流")

      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith("data: ")) continue

          try {
            const event: ExtractEvent = JSON.parse(trimmed.slice(6))
            switch (event.type) {
              case "status":
                setExtractAttempt(event.attempt ?? 0)
                setExtractMaxRetries(event.max_retries ?? 0)
                setExtractProgress(`第 ${event.attempt}/${event.max_retries} 次尝试…`)
                break
              case "retry":
                setExtractAttempt(event.attempt ?? 0)
                setExtractProgress(
                  `第 ${event.attempt} 次失败，${event.delay ?? 0}s 后重试…`
                )
                break
              case "chunk":
                setExtractProgress("解析 AI 响应…")
                break
              case "result":
                setExtractProgress("提取完成 ✓")
                toast.success(`提取成功：${event.title ?? paperId}`)
                break
              case "error":
                setExtractProgress(`提取失败：${event.message ?? "未知错误"}`)
                toast.error(event.message ?? "提取失败")
                break
              case "cancelled":
                setExtractProgress("已取消")
                break
              case "done":
                // 流结束，刷新详情
                await fetchDetail()
                onRefresh?.()
                break
            }
          } catch {
            // 忽略 JSON 解析错误
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setExtractProgress("已取消")
      } else {
        const msg = err instanceof Error ? err.message : "提取失败"
        setExtractProgress(msg)
        toast.error(msg)
      }
    } finally {
      setExtracting(false)
      extractAbortRef.current = null
    }
  }, [paperId, extracting, fetchDetail, onRefresh])

  // ── 操作：翻译摘要 ──

  const handleTranslate = useCallback(async () => {
    if (!paperId || translating) return
    setTranslating(true)
    setTranslatingResult(null)
    try {
      const res = await apiPost<{ translation: string; cached: boolean }>(
        `/literature/${paperId}/translate`
      )
      setTranslatingResult(res.translation)
      toast.success(res.cached ? "已加载缓存翻译" : "翻译完成")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "翻译失败")
    } finally {
      setTranslating(false)
    }
  }, [paperId, translating])

  // ── 操作：删除文献 ──

  const handleDelete = useCallback(async () => {
    if (!paperId || deleting) return
    if (!window.confirm("确定要删除这篇文献吗？此操作不可撤销。")) return

    setDeleting(true)
    try {
      await apiDelete(`/literature/${paperId}`)
      toast.success("文献已删除")
      onRefresh?.()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeleting(false)
    }
  }, [paperId, deleting, onRefresh, onClose])

  // ── 标签编辑 ──

  const startEditTags = useCallback(() => {
    if (!paper) return
    setTagInput(paper.tags.join(", "))
    setEditingTags(true)
  }, [paper])

  const saveTags = useCallback(async () => {
    if (!paperId || savingTags) return
    const tags = tagInput
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean)

    setSavingTags(true)
    try {
      const res = await apiPut<{ id: string; tags: string[] }>(
        `/literature/${paperId}/tags`,
        { tags }
      )
      setPaper((prev) => (prev ? { ...prev, tags: res.tags } : null))
      setEditingTags(false)
      toast.success("标签已更新")
      onRefresh?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "标签更新失败")
    } finally {
      setSavingTags(false)
    }
  }, [paperId, tagInput, savingTags, onRefresh])

  const cancelEditTags = useCallback(() => {
    setEditingTags(false)
    if (paper) setTagInput(paper.tags.join(", "))
  }, [paper])

  // ── 折叠面板 ──

  const toggleSection = useCallback((section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(section)) next.delete(section)
      else next.add(section)
      return next
    })
  }, [])

  // ── 摘要渲染 ──

  const renderExtractedData = (data: ExtractedData) => (
    <div className="space-y-3 text-sm">
      {data.background && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
            研究背景
          </h4>
          <p className="text-foreground/90 leading-relaxed">{data.background}</p>
        </div>
      )}
      {data.methods && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
            研究方法
          </h4>
          <p className="text-foreground/90 leading-relaxed">{data.methods}</p>
        </div>
      )}
      {data.key_results && data.key_results.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
            核心结果
          </h4>
          <ul className="list-disc list-inside space-y-1 text-foreground/90">
            {data.key_results.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {data.conclusion && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
            研究结论
          </h4>
          <p className="text-foreground/90 leading-relaxed">{data.conclusion}</p>
        </div>
      )}
      {data.keywords && data.keywords.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
            关键词
          </h4>
          <div className="flex flex-wrap gap-1">
            {data.keywords.map((kw) => (
              <span
                key={kw}
                className="inline-block rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )

  // ── 无 paperId 时 ──

  if (!paperId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <FileSearch className="h-12 w-12 mb-3 opacity-30" />
        <p className="text-sm">请选择一篇文献查看详情</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* ── 顶部操作栏 ── */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5 shrink-0 bg-muted/30">
        <h3 className="text-sm font-semibold truncate max-w-[60%]" title={paper?.title ?? undefined}>
          {loading ? "加载中…" : paper?.title ?? "文献详情"}
        </h3>
        <div className="flex items-center gap-1">
          {/* 重新解析 */}
          <button
            onClick={handleReparse}
            disabled={parsing || !paper}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
            title="重新解析 PDF"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", parsing && "animate-spin")} />
            <span className="hidden sm:inline">重新解析</span>
          </button>

          {/* 提取摘要 */}
          <button
            onClick={handleExtract}
            disabled={extracting || !paper}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
            title="AI 提取摘要"
          >
            {extracting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FileSearch className="h-3.5 w-3.5" />
            )}
            <span className="hidden sm:inline">{extracting ? "提取中…" : "提取摘要"}</span>
          </button>

          {/* 翻译 */}
          <button
            onClick={handleTranslate}
            disabled={translating || !paper || !paper.extracted_data}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
            title="翻译摘要"
          >
            <Languages className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{translating ? "翻译中…" : "翻译"}</span>
          </button>

          {/* 精读对话 */}
          <button
            onClick={() => paperId && onOpenChat?.(paperId)}
            disabled={!paper}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-primary hover:bg-primary/10 transition-colors disabled:opacity-40"
            title="AI 精读对话"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">精读</span>
          </button>

          {/* 删除 */}
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-40"
            title="删除文献"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>

          {/* 关闭 */}
          <button
            onClick={onClose}
            className="ml-2 rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* ── SSE 提取进度条 ── */}
      {extracting && (
        <div className="px-4 py-2 bg-blue-50 dark:bg-blue-950/30 text-xs text-blue-700 dark:text-blue-300 shrink-0">
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {extractProgress}
          </span>
        </div>
      )}

      {/* ── 加载/错误状态 ── */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && !loading && (
        <div className="flex flex-col items-center justify-center py-20 text-destructive">
          <AlertCircle className="h-8 w-8 mb-2" />
          <p className="text-sm">{error}</p>
          <button
            onClick={fetchDetail}
            className="mt-3 text-xs text-primary hover:underline"
          >
            重试
          </button>
        </div>
      )}

      {/* ── 主内容区 ── */}
      {paper && !loading && (
        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：PDF 预览 */}
          <div className="w-[60%] min-w-0 border-r border-border">
            <PdfViewer filePath={paper.file_path} pageCount={paper.page_count} />
          </div>

          {/* 右侧：信息面板 */}
          <div className="w-[40%] min-w-[320px] flex flex-col overflow-y-auto">
            {/* ── 翻译结果（浮动展示） ── */}
            {translatingResult && (
              <div className="mx-3 mt-3 rounded-md border border-border bg-muted/30 p-3">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-semibold text-muted-foreground">中文翻译</h4>
                  <button
                    onClick={() => setTranslatingResult(null)}
                    className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
                <p className="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap">
                  {translatingResult}
                </p>
              </div>
            )}

            {/* ── 摘要 ── */}
            <div className="border-b border-border">
              <button
                onClick={() => toggleSection("summary")}
                className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-muted/30 transition-colors"
              >
                <span>结构化摘要</span>
                {expandedSections.has("summary") ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>
              {expandedSections.has("summary") && (
                <div className="px-4 pb-3">
                  {paper.extracted_data ? (
                    renderExtractedData(paper.extracted_data)
                  ) : (
                    <div className="text-sm text-muted-foreground py-4 text-center">
                      <p>暂无提取数据</p>
                      <p className="text-xs mt-1 opacity-60">
                        点击上方「提取摘要」使用 AI 分析此文献
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* ── 元数据 ── */}
            <div className="border-b border-border">
              <button
                onClick={() => toggleSection("metadata")}
                className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-muted/30 transition-colors"
              >
                <span>文献信息</span>
                {expandedSections.has("metadata") ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>
              {expandedSections.has("metadata") && (
                <div className="px-4 pb-3 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">标题</span>
                    <span className="text-right max-w-[60%] truncate" title={paper.title ?? undefined}>
                      {paper.title ?? "—"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">作者</span>
                    <span className="text-right max-w-[60%] truncate">
                      {paper.authors?.join(", ") ?? "—"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">年份</span>
                    <span>{paper.year ?? "—"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">期刊</span>
                    <span className="text-right max-w-[60%] truncate">
                      {paper.journal ?? "—"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">DOI</span>
                    <span className="text-right max-w-[60%] truncate font-mono text-xs">
                      {paper.doi ?? "—"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">页数</span>
                    <span>{paper.page_count ?? "—"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">文件大小</span>
                    <span>
                      {paper.file_size != null
                        ? `${(paper.file_size / 1024 / 1024).toFixed(2)} MB`
                        : "—"}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">状态</span>
                    <span
                      className={cn(
                        "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                        STATUS_MAP[paper.status]?.className
                      )}
                    >
                      {STATUS_MAP[paper.status]?.label ?? paper.status}
                    </span>
                  </div>
                  {paper.last_error && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">最近错误</span>
                      <span className="text-right max-w-[70%] text-xs text-destructive truncate">
                        {paper.last_error}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* ── 标签 ── */}
            <div className="border-b border-border">
              <button
                onClick={() => toggleSection("tags")}
                className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-muted/30 transition-colors"
              >
                <span>标签</span>
                {expandedSections.has("tags") ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>
              {expandedSections.has("tags") && (
                <div className="px-4 pb-3">
                  {editingTags ? (
                    <div className="space-y-2">
                      <input
                        type="text"
                        value={tagInput}
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") saveTags()
                          if (e.key === "Escape") cancelEditTags()
                        }}
                        placeholder="用逗号分隔多个标签"
                        className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring"
                        autoFocus
                      />
                      <div className="flex items-center gap-1">
                        <button
                          onClick={saveTags}
                          disabled={savingTags}
                          className="inline-flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                        >
                          {savingTags ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Check className="h-3 w-3" />
                          )}
                          保存
                        </button>
                        <button
                          onClick={cancelEditTags}
                          className="rounded px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="flex flex-wrap gap-1 mb-2">
                        {paper.tags.length > 0 ? (
                          paper.tags.map((tag) => (
                            <span
                              key={tag}
                              className="inline-block rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                            >
                              {tag}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-muted-foreground/50">暂无标签</span>
                        )}
                      </div>
                      <button
                        onClick={startEditTags}
                        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <Pencil className="h-3 w-3" />
                        编辑标签
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
