import { useState, useEffect, useCallback } from "react"
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
  Gavel,
  Clock,
  Quote,
} from "lucide-react"
import { toast } from "sonner"
import { cn } from "../lib/utils"
import { apiGet, apiPost, apiPut, apiDelete } from "../api/client"
import { useSSE, type SSEEvent } from "../hooks/useSSE"

import PdfViewer from "./PdfViewer"
import type { PaperDetail, PaperStatus, ExtractedData, ClaimItem, ClaimsListResponse } from "../types"

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

  // ── Claims 列表（文献库内可见结果） ──
  const [claims, setClaims] = useState<ClaimItem[]>([])

  // ── 操作状态 ──
  const [parsing, setParsing] = useState(false)
  const [translating, setTranslating] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [translatingResult, setTranslatingResult] = useState<string | null>(null)

  // ── 提取进度（问题5修复：使用 useSSE 管理） ──
  const [extracting, setExtracting] = useState(false)
  const [extractProgress, setExtractProgress] = useState<string>("")

  // ── Claims 提取状态（A1 + A3 + A4） ──
  const [claimsExtracting, setClaimsExtracting] = useState(false)
  const [claimsProgress, setClaimsProgress] = useState<string>("")
  const [claimsEstimate, setClaimsEstimate] = useState<string | null>(null)
  const [_claimsJobId, setClaimsJobId] = useState<string | null>(null)
  const { start: startClaimsSSE, abort: abortClaimsSSE } = useSSE()

  // ── 标签编辑 ──
  const [editingTags, setEditingTags] = useState(false)
  const [tagInput, setTagInput] = useState("")
  const [savingTags, setSavingTags] = useState(false)

  // ── 折叠面板 ──
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["summary", "metadata"])
  )

  // ── useSSE for extraction（禁用重连，提取流不需要） ──
  const { start: startExtract, abort: abortExtract, isLoading: extractingSSE } = useSSE()

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

  // ── 获取该文献已抽取的 claims（文献库内可见） ──
  const fetchClaims = useCallback(async () => {
    if (!paperId) return
    try {
      const data = await apiGet<ClaimsListResponse>(`/claims/by-paper/${paperId}`)
      setClaims(data.claims)
    } catch {
      setClaims([])
    }
  }, [paperId])

  useEffect(() => {
    fetchDetail()
    fetchClaims()
    return () => {
      // 组件卸载时取消所有 SSE
      abortExtract()
      abortClaimsSSE()
    }
  }, [fetchDetail, fetchClaims, abortExtract, abortClaimsSSE])

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

  // ── 操作：提取摘要（使用 useSSE，禁用重连） ──
  const handleExtract = useCallback(() => {
    if (!paperId || extracting) return

    // 先中止旧的提取
    abortExtract()

    setExtracting(true)
    setExtractProgress("正在连接…")

    startExtract({
      url: `/literature/${paperId}/extract`,
      method: "POST",
      disableRetry: true,   // 提取流不需要重连
      maxRetries: 0,
      onEvent: (event: SSEEvent) => {
        switch (event.type) {
          case "status":
            // 问题6修复：status 只显示"正在提取…"
            setExtractProgress("正在提取…")
            break
          case "retry":
            // 问题6修复：retry 显示重试次数
            setExtractProgress(
              `第 ${event.attempt ?? "?"} 次重试，${event.delay ?? 0}s 后…`
            )
            break
          case "chunk":
            setExtractProgress("解析 AI 响应…")
            break
          case "result": {
            const isPartial = event.partial === true
            const missing = (event.missing_fields as string[] | undefined) ?? []
            if (isPartial) {
              setExtractProgress("部分成功 ✓（部分字段缺失）")
              toast.success(
                `提取部分成功：${(event.title as string) ?? paperId}` +
                  (missing.length ? `（缺：${missing.join("、")}）` : "")
              )
            } else {
              setExtractProgress("提取完成 ✓")
              toast.success(`提取成功：${(event.title as string) ?? paperId}`)
            }
            break
          }
          case "error":
            setExtractProgress(`提取失败：${(event.message as string) ?? "未知错误"}`)
            toast.error((event.message as string) ?? "提取失败")
            break
          case "cancelled":
            setExtractProgress("已取消")
            break
          case "done":
            // 流结束，刷新详情
            fetchDetail()
            onRefresh?.()
            break
        }
      },
      onError: (msg: string) => {
        setExtractProgress(msg)
        toast.error(msg)
      },
      onDone: () => {
        setExtracting(false)
      },
    })
  }, [paperId, extracting, abortExtract, startExtract, fetchDetail, onRefresh])

  // 同步 extracting 状态（对接 useSSE 的 isLoading）
  useEffect(() => {
    if (!extractingSSE && extracting) {
      setExtracting(false)
    }
  }, [extractingSSE, extracting])

  // ── A1: 提取 Claims（项目级 Job，防重抽自动跳过） ──
  const handleExtractClaims = useCallback(async () => {
    if (!paper || claimsExtracting) return
    const projectId = paper.project_id
    if (!projectId) {
      toast.error("该文献未关联项目，请先归入项目再提取 Claims")
      return
    }

    setClaimsExtracting(true)
    setClaimsProgress("正在创建提取任务…")
    setClaimsEstimate(null)

    try {
      // A4: 先获取耗时预估
      const estRes = await apiGet<{ paper_count: number; estimate: Record<string, unknown> }>(
        `/claims/estimate?paper_count=1`
      )
      const est = estRes.estimate as Record<string, string>
      if (est.total_minutes) {
        const mins = parseFloat(est.total_minutes)
        if (mins > 5) {
          setClaimsEstimate(`预计约 ${Math.round(mins)} 分钟（论断抽取推荐用快模型如 deepseek-v4-flash）`)
        } else {
          setClaimsEstimate(`预计约 ${Math.round(mins)} 分钟`)
        }
      }

      // 创建 Job
      const startRes = await apiPost<{
        job_id: string; status: string; pending_paper_count: number; model: string; estimate: Record<string, unknown>
      }>(`/projects/${projectId}/claims-extract/start`, { force: false })

      setClaimsJobId(startRes.job_id)
      setClaimsProgress(`已提交任务 · ${startRes.pending_paper_count} 篇待处理 · 模型: ${startRes.model}`)

      // A3: SSE 订阅进度
      startClaimsSSE({
        url: `/projects/${projectId}/claims-extract/subscribe?job_id=${startRes.job_id}`,
        method: "GET",
        disableRetry: true,
        maxRetries: 0,
        onEvent: (event) => {
          switch (event.type) {
            case "job_status":
              setClaimsProgress(`任务状态: ${event.status as string}`)
              break
            case "paper_progress": {
              const idx = event.current as number
              const tot = event.total as number
              const t = event.title as string
              const st = event.status as string
              setClaimsProgress(`第 ${idx}/${tot} 篇 · ${t?.slice(0, 50)} · ${st === "completed" ? "✓" : st === "failed" ? "✗" : "…"}`)
              break
            }
            case "error":
              setClaimsProgress(`错误: ${event.message as string}`)
              toast.error(event.message as string)
              break
            case "job_done": {
              const ok = event.succeeded as number
              const fail = event.failed as number
              setClaimsProgress(`抽取完成 · 成功 ${ok} 篇${fail > 0 ? `，失败 ${fail} 篇` : ""}`)
              toast.success(`Claims 抽取完成: ${ok}/${(ok + fail)} 篇成功`)
              fetchDetail()
              fetchClaims()
              onRefresh?.()
              break
            }
          }
        },
        onError: (msg) => {
          setClaimsProgress(`连接失败: ${msg}`)
          toast.error(msg)
        },
        onDone: () => {
          setClaimsExtracting(false)
        },
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建 Claims 提取任务失败")
      setClaimsExtracting(false)
    }
  }, [paper, claimsExtracting, startClaimsSSE, fetchDetail, fetchClaims, onRefresh])

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

          {/* A1: 提取 Claims */}
          <button
            onClick={handleExtractClaims}
            disabled={claimsExtracting || !paper}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-purple-600 dark:text-purple-400 hover:text-purple-700 dark:hover:text-purple-300 hover:bg-purple-50 dark:hover:bg-purple-950/30 transition-colors disabled:opacity-40"
            title="AI 提取论断（Claims）用于局限分析"
          >
            {claimsExtracting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Gavel className="h-3.5 w-3.5" />
            )}
            <span className="hidden sm:inline">{claimsExtracting ? "提取中…" : "提取Claims"}</span>
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

      {/* A3: Claims 提取 SSE 进度条 */}
      {claimsExtracting && (
        <div className="space-y-0 shrink-0">
          <div className="px-4 py-2 bg-purple-50 dark:bg-purple-950/30 text-xs text-purple-700 dark:text-purple-300">
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {claimsProgress}
            </span>
          </div>
          {/* A4: 模型耗时提示 */}
          {claimsEstimate && (
            <div className="px-4 py-1.5 bg-amber-50 dark:bg-amber-950/20 text-[0.65rem] text-amber-700 dark:text-amber-400 border-b border-amber-100 dark:border-amber-900/50">
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {claimsEstimate}
              </span>
            </div>
          )}
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
          {/* 左侧：PDF 预览（问题5：传递 paperId 给 PdfViewer） */}
          <div className="w-[60%] min-w-0 border-r border-border">
            <PdfViewer
              filePath={paper.file_path}
              pageCount={paper.page_count}
              paperId={paper.id}
            />
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

            {/* ── 论断 Claims（文献库内可见结果） ── */}
            <div className="border-b border-border">
              <button
                onClick={() => toggleSection("claims")}
                className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-muted/30 transition-colors"
              >
                <span className="inline-flex items-center gap-1.5">
                  <Quote className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />
                  论断 Claims
                  {claims.length > 0 && (
                    <span className="rounded-full bg-purple-100 px-1.5 py-0.5 text-xs font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                      {claims.length}
                    </span>
                  )}
                </span>
                {expandedSections.has("claims") ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>
              {expandedSections.has("claims") && (
                <div className="px-4 pb-3">
                  {claims.length > 0 ? (
                    <ul className="space-y-2">
                      {claims.map((c) => (
                        <li
                          key={c.id}
                          className="rounded-md border border-border bg-muted/20 p-2.5 text-sm"
                        >
                          <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs">
                            {c.topic && (
                              <span className="rounded bg-primary/10 px-1.5 py-0.5 text-primary">
                                {c.topic}
                              </span>
                            )}
                            {c.is_limitation && (
                              <span className="rounded bg-orange-100 px-1.5 py-0.5 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300">
                                局限
                              </span>
                            )}
                            {c.stat_support && (
                              <span className="rounded bg-green-100 px-1.5 py-0.5 text-green-700 dark:bg-green-900/30 dark:text-green-300">
                                统计支持
                              </span>
                            )}
                            <span className="ml-auto text-muted-foreground">P{c.quote_page}</span>
                          </div>
                          {c.subject && (
                            <p className="mb-0.5 text-xs text-muted-foreground">
                              对象：{c.subject}
                            </p>
                          )}
                          <p className="text-foreground/90 leading-relaxed">「{c.quote}」</p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="py-4 text-center text-sm text-muted-foreground">
                      <p>暂无 claims</p>
                      <p className="mt-1 text-xs opacity-60">
                        点击上方「提取Claims」抽取本文献论断
                      </p>
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
