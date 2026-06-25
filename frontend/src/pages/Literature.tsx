import { useState, useEffect, useCallback, useRef } from "react"
import { useSearchParams, useNavigate } from "react-router-dom"
import FileUploader from "../components/FileUploader"
import LiteratureList from "../components/LiteratureList"
import LiteratureDetail from "../components/LiteratureDetail"
import ChatPanel from "../components/ChatPanel"
import { apiGet, apiPost } from "../api/client"
import { useSSE } from "../hooks/useSSE"
import { toast } from "sonner"
import { Gavel, GitBranch, Loader2, Clock } from "lucide-react"
import { COMING_SOON_MESSAGE } from "../components/ComingSoon"
import type { Project, ProjectListResponse, ClaimsExtractStartResponse } from "../types"

// ============================================================================
// Chat 模式
// ============================================================================

type ChatMode =
  | { mode: "single"; paperId: string }
  | { mode: "multi"; paperIds: string[] }
  | null

// ============================================================================
// 常量
// ============================================================================

const LAST_PROJECT_KEY = "ra_last_project_id"

// ============================================================================
// Literature 页面
// ============================================================================

export default function Literature() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigation = useNavigate()
  const leftPanelRef = useRef<HTMLDivElement>(null)
  const projectFilter = searchParams.get("project_id") ?? ""

  const [refreshKey, setRefreshKey] = useState(0)
  const [projects, setProjects] = useState<Project[]>([])
  const [pendingClaimsCount, setPendingClaimsCount] = useState<number | null>(null)

  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [detailPaperId, setDetailPaperId] = useState<string | null>(null)
  const [chatMode, setChatMode] = useState<ChatMode>(null)

  // ── A1: 项目级 Claims 提取 ──
  const [claimsExtracting, setClaimsExtracting] = useState(false)
  const [claimsProgress, setClaimsProgress] = useState("")
  const [claimsEstimate, setClaimsEstimate] = useState<string | null>(null)
  // 独立 useSSE 实例用于 Job 进度（不影响详情页的 useSSE）
  const { start: startClaimsSSE, abort: abortClaimsSSE } = useSSE()

  useEffect(() => {
    apiGet<ProjectListResponse>("/projects/?page=1&page_size=100")
      .then((res) => setProjects(res.items))
      .catch(() => setProjects([]))
  }, [refreshKey])

  // 默认选中项目（记住上次选择，否则选默认项目）
  useEffect(() => {
    if (projects.length === 0) return
    if (searchParams.get("project_id")) return

    const saved = localStorage.getItem(LAST_PROJECT_KEY)
    const validSaved = saved && projects.some((p) => p.id === saved)
    const defaultProject = projects.find((p) => p.is_default) ?? projects[0]
    const id = validSaved ? saved! : defaultProject?.id
    if (id) {
      setSearchParams({ project_id: id })
    }
  }, [projects, searchParams, setSearchParams])

  // 加载待抽 claims 文献数
  useEffect(() => {
    if (!projectFilter) {
      setPendingClaimsCount(null)
      return
    }
    apiGet<{ pending_count: number }>(
      `/projects/${projectFilter}/claims-extract/pending-count`
    )
      .then((res) => setPendingClaimsCount(res.pending_count))
      .catch(() => setPendingClaimsCount(null))
  }, [projectFilter, refreshKey])

  // 清理 SSE
  useEffect(() => {
    return () => {
      abortClaimsSSE()
    }
  }, [abortClaimsSSE])

  const handleProjectFilterChange = useCallback(
    (projectId: string) => {
      if (projectId) {
        localStorage.setItem(LAST_PROJECT_KEY, projectId)
        setSearchParams({ project_id: projectId })
      } else {
        localStorage.removeItem(LAST_PROJECT_KEY)
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

  const handleDeleted = useCallback(
    (deletedIds: string[]) => {
      if (detailPaperId && deletedIds.includes(detailPaperId)) {
        setDetailPaperId(null)
        setChatMode(null)
      }
      handleRefresh()
      leftPanelRef.current?.scrollTo({ top: 0 })
    },
    [detailPaperId, handleRefresh]
  )

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
              const idx = event.current as number
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
  // 信号发现模块（局限聚类→裁决）本版未发布，入口统一占位，不再发起任何网络请求。
  // 后端 /projects/{id}/clustering/limitation 路由与服务保留，将来就绪后换回真实实现即可。
  const handleProjectCluster = useCallback(() => {
    toast(COMING_SOON_MESSAGE)
  }, [])

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
        ref={leftPanelRef}
        className="flex flex-col min-w-0 overflow-y-auto p-6"
        style={{
          width: leftWidth,
          transition: "width 0.2s ease",
        }}
      >
        <FileUploader
          onUploadComplete={handleUploadComplete}
          projects={projects}
          defaultProjectId={projectFilter}
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

              {/* A1: 批量提取 Claims */}
              <button
                onClick={handleProjectExtractClaims}
                disabled={claimsExtracting}
                className="inline-flex items-center gap-1.5 rounded-md border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-950/30 px-3 py-1.5 text-xs font-medium text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-950/50 transition-colors disabled:opacity-40"
                title={
                  pendingClaimsCount !== null
                    ? `本项目 ${pendingClaimsCount} 篇文献待抽取 Claims`
                    : undefined
                }
              >
                {claimsExtracting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Gavel className="h-3.5 w-3.5" />
                )}
                批量提取Claims(本项目)
                {pendingClaimsCount !== null && (
                  <span className="text-purple-500/80 dark:text-purple-400/80">
                    · {pendingClaimsCount} 篇待抽
                  </span>
                )}
              </button>

              {/* A2: 分析局限（聚类）— 本版未发布，点击仅提示"敬请期待" */}
              <button
                onClick={handleProjectCluster}
                className="inline-flex items-center gap-1.5 rounded-md border border-cyan-200 dark:border-cyan-800 bg-cyan-50 dark:bg-cyan-950/30 px-3 py-1.5 text-xs font-medium text-cyan-700 dark:text-cyan-300 hover:bg-cyan-100 dark:hover:bg-cyan-950/50 transition-colors disabled:opacity-40"
              >
                <GitBranch className="h-3.5 w-3.5" />
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
          onDeleted={handleDeleted}
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
