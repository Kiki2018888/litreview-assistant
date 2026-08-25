// ============================================================================
// 机会 / Signals 工作台
// Discover → 待裁决候选 → 采纳/否决 → 已采纳 Signal（证据链）
// ============================================================================

import { useState, useEffect, useCallback, useMemo, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  FileText,
  GitBranch,
  Loader2,
  Search,
  Sparkles,
  X,
} from "lucide-react"
import { toast } from "sonner"

import {
  adjudicate,
  discoverOpportunities,
  downloadAcceptedSignalsMarkdown,
  getCandidateGroup,
  getJobStatus,
  getProjectClaimsTotal,
  getSignalDetail,
  listCandidateGroups,
  listSignals,
  parseJobIdFromError,
  type TypeFilter,
} from "../api/signals"
import { apiGet } from "../api/client"
import { cn } from "../lib/utils"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Card, CardContent } from "../components/ui/card"
import { Input } from "../components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog"
import type {
  CandidateGroup,
  CandidateGroupDetail,
  DiscoverResponse,
  EvidenceItem,
  JobStatusResponse,
  Project,
  ProjectListResponse,
  Signal,
  SignalDetail,
} from "../types"

const LAST_PROJECT_KEY = "ra_last_project_id"

type MainTab = "pending" | "accepted"
type Selection =
  | { kind: "candidate"; id: string }
  | { kind: "signal"; id: string }
  | null

const TYPE_LABEL: Record<string, string> = {
  limitation_cluster: "局限聚类",
  contradiction: "矛盾",
}

const PHASE_LABEL: Record<string, string> = {
  limitation_cluster: "正在聚类局限…",
  contradiction: "正在检测矛盾…",
  persist: "正在写入候选…",
  done: "发现完成",
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function candidateTypeOf(item: { type?: string | null; candidate_type?: string | null }) {
  return item.candidate_type || item.type || "limitation_cluster"
}

function oneLiner(item: { statement?: string | null; group_label?: string | null; signal_name?: string | null }) {
  return (item.statement || item.signal_name || item.group_label || "（无陈述）").trim()
}

function evidencePage(ev: Pick<EvidenceItem, "page" | "quote_page">) {
  const page = ev.page ?? ev.quote_page
  return page && page > 0 ? page : null
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success("已复制陈述")
  } catch {
    toast.error("复制失败")
  }
}

function jobProgressText(job: JobStatusResponse | null, fallback: string) {
  if (!job) return fallback
  const summary = job.error_summary ?? {}
  const phase = typeof summary.phase === "string" ? summary.phase : ""
  const error = typeof summary.error === "string" ? summary.error : ""
  if (job.status === "failed") return error || "发现任务失败"
  if (phase && PHASE_LABEL[phase]) {
    return `${PHASE_LABEL[phase]}（${job.current}/${job.total}）`
  }
  return `${fallback} · ${job.status} ${job.current}/${job.total}`
}

// ============================================================================
// 主页面
// ============================================================================

export default function Adjudication() {
  const [searchParams, setSearchParams] = useSearchParams()
  const projectId = searchParams.get("project_id") ?? ""
  const [projects, setProjects] = useState<Project[]>([])

  const setProjectId = useCallback(
    (id: string) => {
      if (id) {
        localStorage.setItem(LAST_PROJECT_KEY, id)
        setSearchParams({ project_id: id })
      } else {
        setSearchParams({})
      }
    },
    [setSearchParams],
  )

  useEffect(() => {
    apiGet<ProjectListResponse>("/projects/?page=1&page_size=100")
      .then((res) => setProjects(res.items))
      .catch(() => setProjects([]))
  }, [])

  useEffect(() => {
    if (projects.length === 0) return
    if (projectId && projects.some((p) => p.id === projectId)) return
    const saved = localStorage.getItem(LAST_PROJECT_KEY)
    const validSaved = saved && projects.some((p) => p.id === saved)
    const fallback = projects.find((p) => p.is_default) ?? projects[0]
    const id = validSaved ? saved! : fallback?.id
    if (!id) return
    const handle = window.setTimeout(() => setProjectId(id), 0)
    return () => window.clearTimeout(handle)
  }, [projects, projectId, setProjectId])

  if (!projectId) {
    return (
      <div className="p-6 text-sm text-muted-foreground">加载项目…</div>
    )
  }

  return (
    <SignalsWorkbench
      key={projectId}
      projectId={projectId}
      projects={projects}
      onProjectChange={setProjectId}
    />
  )
}

function SignalsWorkbench({
  projectId,
  projects,
  onProjectChange,
}: {
  projectId: string
  projects: Project[]
  onProjectChange: (id: string) => void
}) {
  const [tab, setTab] = useState<MainTab>("pending")
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all")
  const [showWeak, setShowWeak] = useState(false)
  const [allowWeakAccept, setAllowWeakAccept] = useState(false)

  const [candidates, setCandidates] = useState<CandidateGroup[]>([])
  const [hiddenWeakCount, setHiddenWeakCount] = useState(0)
  const [signals, setSignals] = useState<Signal[]>([])
  const [claimsTotal, setClaimsTotal] = useState<number | null>(null)
  const [loadingList, setLoadingList] = useState(false)

  const [selection, setSelection] = useState<Selection>(null)
  const [candidateDetail, setCandidateDetail] = useState<CandidateGroupDetail | null>(null)
  const [signalDetail, setSignalDetail] = useState<SignalDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [discovering, setDiscovering] = useState(false)
  const [jobProgress, setJobProgress] = useState("")
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null)
  const [jobError, setJobError] = useState("")
  const [exporting, setExporting] = useState(false)
  const [lastDiscover, setLastDiscover] = useState<DiscoverResponse | null>(null)

  const [rejectRationale, setRejectRationale] = useState("")
  const [acting, setActing] = useState(false)
  const [weakConfirmOpen, setWeakConfirmOpen] = useState(false)

  const currentProject = projects.find((p) => p.id === projectId)

  const refreshLists = useCallback(async () => {
    if (!projectId) return
    setLoadingList(true)
    try {
      const [pending, accepted, total] = await Promise.all([
        listCandidateGroups(projectId, {
          type: typeFilter,
          status: "pending",
          is_weak: showWeak ? undefined : false,
        }),
        listSignals(projectId, { status: "accepted", type: typeFilter }),
        getProjectClaimsTotal(projectId),
      ])
      setCandidates(pending)
      setSignals(accepted)
      setClaimsTotal(total)
      if (!showWeak && pending.length === 0) {
        const weak = await listCandidateGroups(projectId, {
          type: typeFilter,
          status: "pending",
          is_weak: true,
        })
        setHiddenWeakCount(weak.length)
      } else {
        setHiddenWeakCount(0)
      }
    } catch {
      toast.error("加载候选 / Signal 失败")
      setCandidates([])
      setSignals([])
    } finally {
      setLoadingList(false)
    }
  }, [projectId, typeFilter, showWeak])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void refreshLists()
    }, 0)
    return () => window.clearTimeout(handle)
  }, [refreshLists])

  useEffect(() => {
    if (!projectId || !selection) return
    let cancelled = false
    const handle = window.setTimeout(() => {
      setDetailLoading(true)
      setRejectRationale("")
      const load = async () => {
        try {
          if (selection.kind === "candidate") {
            const detail = await getCandidateGroup(projectId, selection.id)
            if (!cancelled) {
              setCandidateDetail(detail)
              setSignalDetail(null)
            }
          } else {
            const detail = await getSignalDetail(projectId, selection.id)
            if (!cancelled) {
              setSignalDetail(detail)
              setCandidateDetail(null)
            }
          }
        } catch {
          if (!cancelled) {
            toast.error("加载详情失败")
            setCandidateDetail(null)
            setSignalDetail(null)
          }
        } finally {
          if (!cancelled) setDetailLoading(false)
        }
      }
      void load()
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [projectId, selection])

  const pollJob = useCallback(
    async (jobId: string) => {
      for (let i = 0; i < 40; i += 1) {
        const status = await getJobStatus(jobId)
        setJobStatus(status)
        setJobProgress(jobProgressText(status, "发现任务进行中"))
        const summary = status.error_summary ?? {}
        if (status.status === "failed") {
          const err = typeof summary.error === "string" ? summary.error : "发现任务失败"
          setJobError(err)
          toast.error(err)
          return
        }
        if (status.status === "completed" || status.status === "cancelled") {
          setJobError("")
          toast.success("发现任务已结束")
          await refreshLists()
          return
        }
        await sleep(1000)
      }
      setJobError("发现任务超时，请稍后刷新查看结果")
    },
    [refreshLists],
  )

  const handleDiscover = useCallback(async () => {
    if (!projectId || discovering) return
    setDiscovering(true)
    setJobError("")
    setJobStatus(null)
    setLastDiscover(null)
    setJobProgress("正在发现机会（局限聚类 + 矛盾检测）…")
    try {
      const result = await discoverOpportunities(projectId)
      setLastDiscover(result)
      try {
        const status = await getJobStatus(result.job_id)
        setJobStatus(status)
        setJobProgress(jobProgressText(status, "发现完成"))
      } catch {
        setJobProgress("发现完成")
      }
      const hiddenNote =
        result.weak_count > 0 && !showWeak
          ? `，弱候选 ${result.weak_count} 条默认隐藏`
          : result.weak_count
            ? `，弱候选 ${result.weak_count}`
            : ""
      toast.success(
        `发现完成：局限聚类 ${result.limitation_groups} · 矛盾 ${result.contradiction_groups}${hiddenNote}`,
      )
      await refreshLists()
    } catch (err) {
      const message = err instanceof Error ? err.message : "发现失败"
      const existingId = parseJobIdFromError(message)
      if (existingId) {
        setJobProgress("已有发现任务进行中，正在同步进度…")
        try {
          await pollJob(existingId)
        } catch (pollErr) {
          const pollMsg = pollErr instanceof Error ? pollErr.message : message
          setJobError(pollMsg)
          toast.error(pollMsg)
        }
      } else {
        setJobError(message)
        toast.error(message)
      }
    } finally {
      setDiscovering(false)
    }
  }, [projectId, discovering, showWeak, refreshLists, pollJob])

  const closeDetail = useCallback(() => {
    setSelection(null)
    setAllowWeakAccept(false)
    setWeakConfirmOpen(false)
  }, [])

  const handleAccept = useCallback(
    async (acceptWeak: boolean) => {
      if (!projectId || !candidateDetail) return
      setActing(true)
      try {
        await adjudicate(projectId, {
          action: "accept",
          candidate_group_id: candidateDetail.id,
          accept_weak: acceptWeak,
        })
        toast.success("已采纳为 Signal，可在「已采纳 Signal」中查看")
        setWeakConfirmOpen(false)
        closeDetail()
        await refreshLists()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "采纳失败")
      } finally {
        setActing(false)
      }
    },
    [projectId, candidateDetail, closeDetail, refreshLists],
  )

  const handleReject = useCallback(async () => {
    if (!projectId || !candidateDetail) return
    setActing(true)
    try {
      await adjudicate(projectId, {
        action: "reject",
        candidate_group_id: candidateDetail.id,
        human_rationale: rejectRationale.trim() || undefined,
      })
      toast.success("已否决该候选")
      closeDetail()
      await refreshLists()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "否决失败")
    } finally {
      setActing(false)
    }
  }, [projectId, candidateDetail, rejectRationale, closeDetail, refreshLists])

  const handleExport = useCallback(async () => {
    if (!projectId || exporting) return
    setExporting(true)
    try {
      const filename = await downloadAcceptedSignalsMarkdown(projectId)
      toast.success(`已导出 ${filename}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "导出 Markdown 失败")
    } finally {
      setExporting(false)
    }
  }, [projectId, exporting])

  const emptyKind = useMemo(() => {
    if (tab !== "pending") return null
    if (loadingList) return null
    if (candidates.length > 0) return null
    if (claimsTotal === 0) return "no-extracts" as const
    if (hiddenWeakCount > 0 && !showWeak) return "hidden-weak" as const
    if (lastDiscover && lastDiscover.total_candidate_groups === 0) return "discover-empty" as const
    if (signals.length === 0) return "need-discover" as const
    return "caught-up" as const
  }, [
    tab,
    loadingList,
    candidates.length,
    claimsTotal,
    hiddenWeakCount,
    showWeak,
    lastDiscover,
    signals.length,
  ])

  return (
    <div className="flex h-full min-h-0">
      <div
        className={cn(
          "flex-1 min-w-0 overflow-y-auto p-6 space-y-4",
          selection && "hidden lg:block",
        )}
      >
        <Header
          projects={projects}
          projectId={projectId}
          currentName={currentProject?.name}
          discovering={discovering}
          onProjectChange={onProjectChange}
          onDiscover={handleDiscover}
        />

        {(discovering || jobProgress || jobError || lastDiscover) && (
          <DiscoverBanner
            discovering={discovering}
            progress={jobProgress}
            error={jobError}
            last={lastDiscover}
            job={jobStatus}
          />
        )}

        <div className="flex flex-wrap items-center gap-2">
          <TabButton active={tab === "pending"} onClick={() => { setTab("pending"); closeDetail() }}>
            待裁决候选
            <span className="text-[0.65rem] opacity-70">{candidates.length}</span>
          </TabButton>
          <TabButton active={tab === "accepted"} onClick={() => { setTab("accepted"); closeDetail() }}>
            已采纳 Signal
            <span className="text-[0.65rem] opacity-70">{signals.length}</span>
          </TabButton>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {(["all", "limitation_cluster", "contradiction"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setTypeFilter(key)}
              className={cn(
                "px-2.5 py-1 text-xs rounded-md border transition-colors",
                typeFilter === key
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-background text-muted-foreground border-border hover:border-primary/50",
              )}
            >
              {key === "all" ? "全部类型" : TYPE_LABEL[key]}
            </button>
          ))}
          {tab === "pending" && (
            <label className="ml-auto inline-flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={showWeak}
                onChange={(e) => setShowWeak(e.target.checked)}
                className="rounded border-input"
              />
              显示弱候选
            </label>
          )}
          {tab === "accepted" && (
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              disabled={!projectId || exporting}
              onClick={() => void handleExport()}
            >
              {exporting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              导出 Markdown
            </Button>
          )}
        </div>

        {tab === "pending" && (
          <PendingList
            loading={loadingList}
            candidates={candidates}
            emptyKind={emptyKind}
            hiddenWeakCount={hiddenWeakCount}
            projectId={projectId}
            selectedId={selection?.kind === "candidate" ? selection.id : null}
            onSelect={(id) => setSelection({ kind: "candidate", id })}
            onShowWeak={() => setShowWeak(true)}
          />
        )}

        {tab === "accepted" && (
          <AcceptedList
            loading={loadingList}
            signals={signals}
            selectedId={selection?.kind === "signal" ? selection.id : null}
            onSelect={(id) => setSelection({ kind: "signal", id })}
          />
        )}
      </div>

      {selection && (
        <aside className="w-full lg:w-[440px] lg:shrink-0 border-l border-border bg-background overflow-y-auto">
          <DetailPanel
            loading={detailLoading}
            candidate={selection.kind === "candidate" ? candidateDetail : null}
            signal={selection.kind === "signal" ? signalDetail : null}
            acting={acting}
            rejectRationale={rejectRationale}
            onRejectRationale={setRejectRationale}
            allowWeakAccept={allowWeakAccept}
            onAllowWeakAccept={setAllowWeakAccept}
            onClose={closeDetail}
            onAccept={() => {
              if (candidateDetail?.is_weak) {
                if (!allowWeakAccept) return
                setWeakConfirmOpen(true)
              } else {
                void handleAccept(false)
              }
            }}
            onReject={() => void handleReject()}
          />
        </aside>
      )}

      <Dialog open={weakConfirmOpen} onOpenChange={setWeakConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>采纳弱候选？</DialogTitle>
            <DialogDescription>
              该候选缺少完整 quote+页码证据，将以 accept_weak=true 提交。请确认你已看过证据后再采纳。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setWeakConfirmOpen(false)}>
              取消
            </Button>
            <Button size="sm" disabled={acting} onClick={() => void handleAccept(true)}>
              <Check className="h-3.5 w-3.5" />
              确认采纳
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ============================================================================
// 子组件
// ============================================================================

function Header({
  projects,
  projectId,
  currentName,
  discovering,
  onProjectChange,
  onDiscover,
}: {
  projects: Project[]
  projectId: string
  currentName?: string
  discovering: boolean
  onProjectChange: (id: string) => void
  onDiscover: () => void
}) {
  return (
    <div className="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h1 className="text-xl font-bold tracking-tight">机会 / Signals</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          发现局限聚类与矛盾候选，由你裁决哪些成为 Signal。AI 只召回，不下结论。
        </p>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={projectId}
          onChange={(e) => onProjectChange(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-1.5 text-xs outline-none focus:border-ring focus:ring-1 focus:ring-ring min-w-[10rem]"
        >
          {projects.length === 0 && <option value="">暂无项目</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {p.is_default ? "（默认）" : ""}
            </option>
          ))}
        </select>
        <Button size="sm" disabled={!projectId || discovering} onClick={onDiscover}>
          {discovering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          发现机会
        </Button>
      </div>
      {currentName && (
        <p className="w-full text-[0.7rem] text-muted-foreground -mt-2">
          当前项目：{currentName}
        </p>
      )}
    </div>
  )
}

function DiscoverBanner({
  discovering,
  progress,
  error,
  last,
  job,
}: {
  discovering: boolean
  progress: string
  error: string
  last: DiscoverResponse | null
  job: JobStatusResponse | null
}) {
  if (error) {
    return (
      <div className="px-3 py-2 rounded-md border border-destructive/30 bg-destructive/5 text-xs text-destructive">
        {error}
      </div>
    )
  }
  if (discovering) {
    return (
      <div className="px-3 py-2 rounded-md bg-cyan-50 dark:bg-cyan-950/30 text-xs text-cyan-800 dark:text-cyan-300">
        <span className="inline-flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {progress || "正在发现机会…"}
        </span>
      </div>
    )
  }
  if (last) {
    return (
      <div className="px-3 py-2 rounded-md bg-muted text-xs text-muted-foreground">
        上次发现：局限聚类 {last.limitation_groups} · 矛盾 {last.contradiction_groups} ·
        主路径 {last.primary_count} · 弱候选 {last.weak_count}
        {job?.error_summary && typeof job.error_summary.phase === "string"
          ? ` · 阶段 ${job.error_summary.phase}`
          : ""}
      </div>
    )
  }
  if (progress) {
    return (
      <div className="px-3 py-2 rounded-md bg-muted text-xs text-muted-foreground">{progress}</div>
    )
  }
  return null
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border transition-colors",
        active
          ? "bg-primary text-primary-foreground border-primary"
          : "bg-background text-muted-foreground border-border hover:border-primary/50",
      )}
    >
      {children}
    </button>
  )
}

function PendingList({
  loading,
  candidates,
  emptyKind,
  hiddenWeakCount,
  projectId,
  selectedId,
  onSelect,
  onShowWeak,
}: {
  loading: boolean
  candidates: CandidateGroup[]
  emptyKind: "no-extracts" | "hidden-weak" | "need-discover" | "discover-empty" | "caught-up" | null
  hiddenWeakCount: number
  projectId: string
  selectedId: string | null
  onSelect: (id: string) => void
  onShowWeak: () => void
}) {
  if (loading) {
    return <p className="text-sm text-muted-foreground py-10 text-center">加载中…</p>
  }
  if (candidates.length === 0) {
    return (
      <EmptyPending
        kind={emptyKind}
        hiddenWeakCount={hiddenWeakCount}
        projectId={projectId}
        onShowWeak={onShowWeak}
      />
    )
  }
  return (
    <div className="space-y-3">
      {candidates.map((cg) => {
        const ctype = candidateTypeOf(cg)
        return (
          <Card
            key={cg.id}
            className={cn(
              "hover:border-primary/30 transition-colors cursor-pointer",
              selectedId === cg.id && "border-primary/60 ring-1 ring-primary/20",
            )}
            onClick={() => onSelect(cg.id)}
          >
            <CardContent className="p-4 space-y-2">
              <p className="text-sm font-medium leading-snug">{oneLiner(cg)}</p>
              <div className="flex items-center gap-1.5 flex-wrap">
                <TypeBadge type={ctype} />
                {cg.is_weak && (
                  <Badge variant="outline" className="text-[0.65rem] text-amber-700 dark:text-amber-400">
                    弱候选
                  </Badge>
                )}
                {cg.previously_rejected && (
                  <Badge variant="secondary" className="text-[0.65rem]">
                    曾被否决
                  </Badge>
                )}
                {cg.cross_paper && (
                  <span className="inline-flex items-center gap-1 text-[0.65rem] text-amber-700 dark:text-amber-400">
                    <GitBranch className="h-3 w-3" />
                    跨论文
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  {cg.claim_count} 条证据
                  {cg.paper_count ? ` · ${cg.paper_count} 篇文献` : ""}
                </span>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function EmptyPending({
  kind,
  hiddenWeakCount,
  projectId,
  onShowWeak,
}: {
  kind: "no-extracts" | "hidden-weak" | "need-discover" | "discover-empty" | "caught-up" | null
  hiddenWeakCount: number
  projectId: string
  onShowWeak: () => void
}) {
  const lit = `/?project_id=${encodeURIComponent(projectId)}`
  if (kind === "no-extracts") {
    return (
      <div className="rounded-lg border border-dashed border-border py-12 px-6 text-center space-y-2">
        <FileText className="h-8 w-8 mx-auto text-muted-foreground/50" />
        <p className="text-sm font-medium">还没有可发现的论断</p>
        <p className="text-xs text-muted-foreground max-w-md mx-auto">
          请先到文献库上传 PDF，并完成摘要 / Claims 抽取，再回到这里点击「发现机会」。
        </p>
        <Link to={lit} className="inline-block text-xs text-primary hover:underline pt-1">
          前往文献库提取 →
        </Link>
      </div>
    )
  }
  if (kind === "hidden-weak") {
    return (
      <div className="rounded-lg border border-dashed border-border py-12 px-6 text-center space-y-2">
        <AlertTriangle className="h-8 w-8 mx-auto text-amber-500/70" />
        <p className="text-sm font-medium">主路径暂无候选</p>
        <p className="text-xs text-muted-foreground">
          有 {hiddenWeakCount} 条弱候选已隐藏（缺少完整 quote / 页码）。
        </p>
        <button type="button" onClick={onShowWeak} className="text-xs text-primary hover:underline">
          显示弱候选
        </button>
      </div>
    )
  }
  if (kind === "discover-empty") {
    return (
      <div className="rounded-lg border border-dashed border-border py-12 px-6 text-center space-y-2">
        <Search className="h-8 w-8 mx-auto text-muted-foreground/50" />
        <p className="text-sm font-medium">本次未发现候选</p>
        <p className="text-xs text-muted-foreground max-w-md mx-auto">
          已有论断，但没有聚成局限组或规则矛盾。可补充 Claims 后再次点击「发现机会」。
        </p>
      </div>
    )
  }
  if (kind === "caught-up") {
    return (
      <p className="text-sm text-muted-foreground py-10 text-center">
        没有待裁决候选。可查看「已采纳 Signal」，或再次点击「发现机会」。
      </p>
    )
  }
  return (
    <div className="rounded-lg border border-dashed border-border py-12 px-6 text-center space-y-2">
      <Sparkles className="h-8 w-8 mx-auto text-muted-foreground/50" />
      <p className="text-sm font-medium">已抽取论断，尚未发现候选</p>
      <p className="text-xs text-muted-foreground">点击右上角「发现机会」开始局限聚类与矛盾检测。</p>
    </div>
  )
}

function AcceptedList({
  loading,
  signals,
  selectedId,
  onSelect,
}: {
  loading: boolean
  signals: Signal[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  if (loading) {
    return <p className="text-sm text-muted-foreground py-10 text-center">加载中…</p>
  }
  if (signals.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border py-12 px-6 text-center space-y-2">
        <Check className="h-8 w-8 mx-auto text-muted-foreground/50" />
        <p className="text-sm font-medium">尚无已采纳 Signal</p>
        <p className="text-xs text-muted-foreground">在「待裁决候选」中采纳后，证据链会出现在这里。</p>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {signals.map((sig) => {
        const ctype = candidateTypeOf(sig)
        return (
          <Card
            key={sig.id}
            className={cn(
              "hover:border-primary/30 transition-colors cursor-pointer",
              selectedId === sig.id && "border-primary/60 ring-1 ring-primary/20",
            )}
            onClick={() => onSelect(sig.id)}
          >
            <CardContent className="p-4 space-y-2">
              <p className="text-sm font-medium leading-snug">{oneLiner(sig)}</p>
              <div className="flex items-center gap-1.5 flex-wrap">
                <TypeBadge type={ctype} />
                <Badge variant="default" className="text-[0.65rem]">已采纳</Badge>
                <span className="text-xs text-muted-foreground">{sig.claim_count} 条证据</span>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function TypeBadge({ type }: { type: string }) {
  const contradiction = type === "contradiction"
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[0.65rem]",
        contradiction
          ? "border-orange-300 text-orange-700 dark:border-orange-800 dark:text-orange-300"
          : "border-cyan-300 text-cyan-700 dark:border-cyan-800 dark:text-cyan-300",
      )}
    >
      {TYPE_LABEL[type] || type}
    </Badge>
  )
}

function DetailPanel({
  loading,
  candidate,
  signal,
  acting,
  rejectRationale,
  onRejectRationale,
  allowWeakAccept,
  onAllowWeakAccept,
  onClose,
  onAccept,
  onReject,
}: {
  loading: boolean
  candidate: CandidateGroupDetail | null
  signal: SignalDetail | null
  acting: boolean
  rejectRationale: string
  onRejectRationale: (v: string) => void
  allowWeakAccept: boolean
  onAllowWeakAccept: (v: boolean) => void
  onClose: () => void
  onAccept: () => void
  onReject: () => void
}) {
  const readOnly = !!signal
  const statement = signal ? oneLiner(signal) : candidate ? oneLiner(candidate) : ""
  const ctype = signal ? candidateTypeOf(signal) : candidate ? candidateTypeOf(candidate) : ""
  const previouslyRejected = candidate?.previously_rejected
  const isWeak = !!candidate?.is_weak
  const evidence: EvidenceItem[] = signal?.evidence?.length
    ? signal.evidence
    : (candidate?.evidence?.length
      ? candidate.evidence
      : (candidate?.claims || []).map((c) => ({
          claim_id: c.claim_id,
          paper_id: c.paper_id,
          paper_title: c.paper_title,
          quote: c.quote,
          page: c.quote_page,
          quote_page: c.quote_page,
          subject: c.subject,
          topic: c.topic,
          direction: c.direction,
          comparison_result: c.comparison_result,
          claim_form: c.claim_form,
        })))

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-start justify-between gap-2 px-4 py-3 border-b border-border">
        <div className="min-w-0 space-y-1.5">
          <p className="text-[0.65rem] uppercase tracking-wider text-muted-foreground">
            {readOnly ? "已采纳 Signal" : "候选详情"}
          </p>
          <h2 className="text-sm font-semibold leading-snug">{statement || "加载中…"}</h2>
          <div className="flex items-center gap-1.5 flex-wrap">
            {ctype && <TypeBadge type={ctype} />}
            {isWeak && (
              <Badge variant="outline" className="text-[0.65rem] text-amber-700 dark:text-amber-400">
                弱候选
              </Badge>
            )}
            {previouslyRejected && (
              <Badge variant="secondary" className="text-[0.65rem]">曾被否决</Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {statement && (
            <Button variant="ghost" size="icon" title="复制陈述" onClick={() => void copyText(statement)}>
              <Copy className="h-4 w-4" />
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {loading && (
          <p className="text-sm text-muted-foreground py-8 text-center inline-flex items-center gap-2 w-full justify-center">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载详情…
          </p>
        )}

        {!loading && (
          <EvidenceList
            evidence={evidence}
            contradiction={ctype === "contradiction"}
          />
        )}

        {readOnly && signal?.human_rationale && (
          <p className="text-xs text-muted-foreground">备注：{signal.human_rationale}</p>
        )}
      </div>

      {!readOnly && candidate && (
        <div className="border-t border-border p-4 space-y-3">
          {isWeak && (
            <label className="flex items-start gap-2 text-xs text-muted-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={allowWeakAccept}
                onChange={(e) => onAllowWeakAccept(e.target.checked)}
                className="mt-0.5 rounded border-input"
              />
              <span>允许弱候选（将以 accept_weak=true 提交；证据不完整，请谨慎）</span>
            </label>
          )}
          <Input
            placeholder="否决理由（可选）"
            value={rejectRationale}
            onChange={(e) => onRejectRationale(e.target.value)}
            className="text-sm"
          />
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              disabled={acting}
              onClick={onReject}
            >
              <X className="h-3.5 w-3.5" />
              否决
            </Button>
            {(!isWeak || allowWeakAccept) && (
              <Button size="sm" className="flex-1" disabled={acting} onClick={onAccept}>
                <Check className="h-3.5 w-3.5" />
                采纳
              </Button>
            )}
          </div>
          {isWeak && !allowWeakAccept && (
            <p className="text-[0.65rem] text-muted-foreground">
              弱候选默认隐藏「采纳」。勾选「允许弱候选」后可继续。
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function EvidenceList({
  evidence,
  contradiction,
}: {
  evidence: EvidenceItem[]
  contradiction: boolean
}) {
  if (evidence.length === 0) {
    return <p className="text-sm text-muted-foreground">无证据</p>
  }
  if (contradiction) {
    const sides = evidence.slice(0, 2)
    const labels = ["一方", "另一方"]
    return (
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          双方证据
        </h3>
        {sides.map((ev, i) => (
          <EvidenceCard
            key={ev.claim_id || i}
            ev={ev}
            label={labels[i]}
            polarity
          />
        ))}
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        证据
      </h3>
      {evidence.map((ev, i) => (
        <EvidenceCard key={ev.claim_id || i} ev={ev} />
      ))}
    </div>
  )
}

function EvidenceCard({
  ev,
  label,
  polarity,
}: {
  ev: EvidenceItem
  label?: string
  polarity?: boolean
}) {
  const page = evidencePage(ev)
  const polarityText = [ev.direction, ev.comparison_result].filter(Boolean).join(" / ")
  return (
    <div className="rounded-md border border-border p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium leading-snug">
          {label ? <span className="text-xs text-muted-foreground mr-1.5">{label}</span> : null}
          {ev.paper_title || "未知文献"}
        </p>
        {page != null && (
          <span className="text-[0.65rem] text-muted-foreground shrink-0">p.{page}</span>
        )}
      </div>
      {polarity && polarityText && (
        <p className="text-[0.65rem] font-medium text-orange-700 dark:text-orange-300">
          {polarityText}
        </p>
      )}
      {ev.subject && (
        <p className="text-[0.65rem] text-cyan-700 dark:text-cyan-300">研究对象：{ev.subject}</p>
      )}
      <blockquote className="border-l-2 border-primary/40 pl-3 text-sm leading-relaxed whitespace-pre-wrap break-words bg-muted/30 py-1.5 rounded-r">
        {ev.quote || "（无原文）"}
      </blockquote>
    </div>
  )
}
