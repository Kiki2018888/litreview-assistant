import { useState, useEffect, useCallback } from "react"
import { useSearchParams, useNavigate } from "react-router-dom"
import FileUploader from "../components/FileUploader"
import LiteratureList from "../components/LiteratureList"
import LiteratureDetail from "../components/LiteratureDetail"
import ChatPanel from "../components/ChatPanel"
import { apiGet, apiPost } from "../api/client"
import { useSSE } from "../hooks/useSSE"
import { toast } from "sonner"
import { Gavel, GitBranch, Loader2, Clock } from "lucide-react"
import type { Project, ProjectListResponse, ClaimsExtractStartResponse } from "../types"

// ============================================================================
// Chat 模式
// ============================================================================

type ChatMode =
  | { mode: "single"; paperId: string }
  | { mode: "multi"; paperIds: string[] }
  | null

// ============================================================================
// Literature 页面
// ============================================================================

export default function Literature() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigation = useNavigate()
  const projectFilter = searchParams.get("project_id") ?? ""

  const [refreshKey, setRefreshKey] = useState(0)
  const [projects, setProjects] = useState<Project[]>([])

  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [detailPaperId, setDetailPaperId] = useState<string | null>(null)
  const [chatMode, setChatMode] = useState<ChatMode>(null)

  // ── A1: 项目级 Claims 提取 ──
  const [claimsExtracting, setClaimsExtracting] = useState(false)
  const [claimsProgress, setClaimsProgress] = useState("")
  const [claimsEstimate, setClaimsEstimate] = useState<string | null>(null)
  // 独立 useSSE 实例用于 Job 进度（不影响详情页的 useSSE）
  const { start: startClaimsSSE, abort: abortClaimsSSE } = useSSE()

  // ── A2: 聚类状态 ──
  const [clustering, setClustering] = useState(false)
  const [clusterProgress, setClusterProgress] = useState("")

  useEffect(() => {
    apiGet<ProjectListResponse>("/projects/?page=1&page_size=100")
      .then((res) => setProjects(res.items))
      .catch(() => setProjects([]))
  }, [refreshKey])

  // 清理 SSE
  useEffect(() => {
    return () => {
      abortClaimsSSE()
    }
  }, [abortClaimsSSE])

  const handleProjectFilterChange = useCallback(
    (projectId: string) => {
      if (projectId) {
        setSearchParams({ project_id: projectId })
      } else {
        setSearchParams({})
      }
    },
    [setSearchParams]
  )

  const handleUploadComplete = useCallback(() => {
    setRefreshKey((k) => k + 1)
    setSelectedIds([])
  }, [])

  const handleCloseDetail = useCallback(() => {
    setDetailPaperId(null)
  }, [])

  const handleRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  const handleOpenChat = useCallback((paperId: string) => {
    setChatMode({ mode: "single", paperId })
  }, [])

  const handleChatMulti = useCallback((paperIds: string[]) => {
    if (paperIds.length === 0) return
    setChatMode({ mode: "multi", paperIds })
  }, [])

  const handleCloseChat = useCallback(() => {
    setChatMode(null)
  }, [])

  // ── A1: 项目级提取 Claims ──
  const handleProjectExtractClaims = useCallback(async () => {
    if (!projectFilter || claimsExtracting) return
    setClaimsExtracting(true)
    setClaimsProgress("正在创建提取任务…")
    setClaimsEstimate(null)

    try {
      // A4: 耗时预估
      const currentProject = projects.find((p) => p.id === projectFilter)
      const paperCount = currentProject?.paper_count ?? 1
      const estRes = await apiGet<{ paper_count: number; estimate: Record<string, unknown> }>(
        `/claims/estimate?paper_count=${paperCount}`
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

      const startRes = await apiPost<ClaimsExtractStartResponse>(
        `/projects/${projectFilter}/claims-extract/start`,
        { force: false }
      )

      setClaimsProgress(`已提交 · ${startRes.pending_paper_count} 篇待处理 · 模型: ${startRes.model}`)

      startClaimsSSE({
        url: `/projects/${projectFilter}/claims-extract/subscribe?job_id=${startRes.job_id}`,
        method: "GET",
        disableRetry: true,
        maxRetries: 0,
        onEvent: (event) => {
          switch (event.type) {
            case "job_status":
              setClaimsProgress(`任务状态: ${event.status as string}`)
              break
            case "paper_progress": {
              const idx = event.index as number
              const tot = event.total as number
              const t = event.title as string
              const st = event.status as string
              setClaimsProgress(`第 ${idx}/${tot} 篇 · ${(t || "").slice(0, 50)} · ${st === "completed" ? "✓" : st === "failed" ? "✗" : "…"}`)
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
              handleRefresh()
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
      toast.error(err instanceof Error ? err.message : "创建提取任务失败")
      setClaimsExtracting(false)
    }
  }, [projectFilter, claimsExtracting, projects, startClaimsSSE, handleRefresh])

  // ── A2: 项目级分析局限（聚类） ──
  const handleProjectCluster = useCallback(async () => {
    if (!projectFilter || clustering) return
    setClustering(true)
    setClusterProgress("正在聚类分析…")

    // 使用 no-cache 避免浏览器缓存
    try {
      const base = "http://localhost:8000/api/v1"  // 因为前端 dev 代理 /api/v1，走相对路径
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 30000) // 28s 后超时
      const res = await fetch(`/api/v1/projects/${projectFilter}/clustering/limitation`, {
        method: "POST",
        signal: ctrl.signal,
      })
      clearTimeout(timeout)

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        const detail = errData.detail || `HTTP ${res.status}`
        if (res.status === 504) {
          toast.error("聚类超时，建议在设置中切换更快模型（如 kimi-k2.6）后重试")
        } else {
          toast.error(`聚类失败: ${detail}`)
        }
        setClusterProgress("")
        setClustering(false)
        return
      }

      const result = await res.json()
      const groupCount = result.total_candidate_groups ?? 0
      const runId = result.run_id ?? ""
      toast.success(`聚类完成：${groupCount} 个候选组`)
      setClusterProgress(`完成 · ${groupCount} 组`)

      // 跳转到裁决面板
      setTimeout(() => {
        navigation(`/adjudication${runId ? `?run_id=${runId}` : ""}`)
      }, 1500)
    } catch (err: any) {
      if (err.name === "AbortError") {
        toast.error("聚类超时，建议在设置中切换更快模型（如 kimi-k2.6）后重试")
      } else {
        toast.error(err instanceof Error ? err.message : "聚类失败")
      }
      setClusterProgress("")
    } finally {
      setClustering(false)
    }
  }, [projectFilter, clustering, navigation])

  const showDetailOnly = detailPaperId !== null && chatMode === null

  const showDetailWithChat =
    detailPaperId !== null &&
    chatMode?.mode === "single" &&
    chatMode.paperId === detailPaperId

  const showChatOnly =
    chatMode !== null && !showDetailWithChat

  const leftWidth =
    showDetailOnly || showDetailWithChat || showChatOnly ? "40%" : "100%"

  return (
    <div className="flex h-full">
      <div
        className="flex flex-col min-w-0 overflow-y-auto p-6"
        style={{
          width: leftWidth,
          transition: "width 0.2s ease",
        }}
      >
        <FileUploader
          onUploadComplete={handleUploadComplete}
          projects={projects}
        />

        <hr className="border-border my-6" />

        {/* A1+A2: 项目级操作条（仅在筛选项目时显示） */}
        {projectFilter && (
          <div className="space-y-2 mb-4">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary/5 border border-primary/20 text-sm font-medium">
                <GitBranch className="h-4 w-4 text-primary" />
                {projects.find((p) => p.id === projectFilter)?.name ?? "当前项目"}
              </div>

              {/* A1: 提取 Claims */}
              <button
                onClick={handleProjectExtractClaims}
                disabled={claimsExtracting || clustering}
                className="inline-flex items-center gap-1.5 rounded-md border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-950/30 px-3 py-1.5 text-xs font-medium text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-950/50 transition-colors disabled:opacity-40"
              >
                {claimsExtracting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Gavel className="h-3.5 w-3.5" />
                )}
                提取Claims
              </button>

              {/* A2: 分析局限（聚类） */}
              <button
                onClick={handleProjectCluster}
                disabled={clustering || claimsExtracting}
                className="inline-flex items-center gap-1.5 rounded-md border border-cyan-200 dark:border-cyan-800 bg-cyan-50 dark:bg-cyan-950/30 px-3 py-1.5 text-xs font-medium text-cyan-700 dark:text-cyan-300 hover:bg-cyan-100 dark:hover:bg-cyan-950/50 transition-colors disabled:opacity-40"
              >
                {clustering ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <GitBranch className="h-3.5 w-3.5" />
                )}
                分析局限
              </button>

              {/* 跳转裁决面板 */}
              <button
                onClick={() => navigation("/adjudication")}
                className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors"
              >
                裁决面板 →
              </button>
            </div>

            {/* A3: Claims 提取进度条 */}
            {claimsExtracting && (
              <div className="space-y-0">
                <div className="px-3 py-1.5 bg-purple-50 dark:bg-purple-950/30 rounded text-xs text-purple-700 dark:text-purple-300">
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {claimsProgress}
                  </span>
                </div>
                {claimsEstimate && (
                  <div className="px-3 py-1 bg-amber-50 dark:bg-amber-950/20 rounded-b text-[0.65rem] text-amber-700 dark:text-amber-400">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {claimsEstimate}
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* A2: 聚类进度条 */}
            {clustering && clusterProgress && (
              <div className="px-3 py-1.5 bg-cyan-50 dark:bg-cyan-950/30 rounded text-xs text-cyan-700 dark:text-cyan-300">
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {clusterProgress}
                </span>
              </div>
            )}
          </div>
        )}

        <LiteratureList
          refreshKey={refreshKey}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onSelectPaper={(id) => {
            setDetailPaperId(id)
            if (chatMode?.mode === "multi") setChatMode(null)
          }}
          onChatMulti={handleChatMulti}
          projects={projects}
          projectFilter={projectFilter}
          onProjectFilterChange={handleProjectFilterChange}
          onDeleted={handleRefresh}
        />
      </div>

      {showDetailOnly && (
        <div
          className="border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          <LiteratureDetail
            paperId={detailPaperId}
            onClose={handleCloseDetail}
            onRefresh={handleRefresh}
            onOpenChat={handleOpenChat}
          />
        </div>
      )}

      {showDetailWithChat && chatMode && (
        <div
          className="flex flex-col border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          <div className="flex-1 overflow-hidden" style={{ flexBasis: "50%" }}>
            <LiteratureDetail
              paperId={detailPaperId}
              onClose={() => {
                setChatMode(null)
                handleCloseDetail()
              }}
              onRefresh={handleRefresh}
              onOpenChat={handleOpenChat}
            />
          </div>

          <div className="flex-1 overflow-hidden border-t border-border">
            <ChatPanel
              mode="single"
              paperId={chatMode.paperId}
              onClose={handleCloseChat}
            />
          </div>
        </div>
      )}

      {showChatOnly && chatMode && (
        <div
          className="border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          {chatMode.mode === "single" ? (
            <ChatPanel
              mode="single"
              paperId={chatMode.paperId}
              onClose={handleCloseChat}
            />
          ) : (
            <ChatPanel
              mode="multi"
              paperIds={chatMode.paperIds}
              onClose={handleCloseChat}
            />
          )}
        </div>
      )}
    </div>
  )
}
