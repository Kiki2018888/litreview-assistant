// ============================================================================
// M5.3 裁决面板 — ADR-7: AI召回候选, 人裁决, AI不下结论
// 视图一: 候选组列表(快速扫)
// 视图二: 单卡详判(面板核心)
// ============================================================================

import { useState, useEffect, useCallback } from "react"
import {
  ArrowLeft,
  Check,
  X,
  Pencil,
  FileText,
  AlertTriangle,
  GitBranch,
} from "lucide-react"
import { toast } from "sonner"

import { apiGet, apiPost, apiDelete, resolveApiBase } from "../api/client"
import { cn } from "../lib/utils"
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../components/ui/dialog"
import type { CandidateGroup, CandidateGroupDetail, Signal, SignalDetail } from "../types"

// ============================================================================
// 视图枚举
// ============================================================================

type View =
  | { mode: "list" }
  | { mode: "detail"; groupId: string }

// ============================================================================
// 工具
// ============================================================================

const STATUS_LABEL: Record<string, string> = {
  pending: "待裁决",
  accepted: "已采纳",
  rejected: "已否决",
}
const STATUS_BADGE: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "secondary",
  accepted: "default",
  rejected: "destructive",
}

function formatCrossPaper(cross: boolean | null | undefined) {
  if (!cross) return null
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50 px-2 py-0.5 rounded border border-amber-200 dark:border-amber-800">
      <GitBranch className="h-3 w-3" />
      跨论文
    </span>
  )
}

// ============================================================================
// 主组件
// ============================================================================

export default function Adjudication() {
  const [view, setView] = useState<View>({ mode: "list" })
  const [refreshKey, setRefreshKey] = useState(0)

  // 列表视图: 跳转到单卡详判
  const goDetail = useCallback((groupId: string) => {
    setView({ mode: "detail", groupId })
  }, [])

  // 返回列表
  const goBack = useCallback(() => {
    setView({ mode: "list" })
    setRefreshKey((k) => k + 1)
  }, [])

  if (view.mode === "detail") {
    return <DetailView groupId={view.groupId} onBack={goBack} />
  }

  return <ListView key={refreshKey} onGoDetail={goDetail} />
}

// ============================================================================
// 视图一 · 候选组列表
// ============================================================================

type FilterTab = "all" | "pending" | "accepted" | "rejected"

function ListView({ onGoDetail }: { onGoDetail: (id: string) => void }) {
  const [groups, setGroups] = useState<CandidateGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterTab>("all")
  const [rejectingId, setRejectingId] = useState<string | null>(null)

  const fetchGroups = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiGet<CandidateGroup[]>("/adjudication/candidate-groups")
      setGroups(data)
    } catch {
      toast.error("获取候选组列表失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchGroups()
  }, [fetchGroups])

  // 快速否决
  const handleQuickReject = useCallback(async (cg: CandidateGroup) => {
    setRejectingId(cg.id)
    try {
      await apiPost("/adjudication/signals", {
        action: "reject",
        candidate_group_id: cg.id,
      })
      toast.success(`已否决候选组: ${cg.group_label.slice(0, 40)}`)
      fetchGroups()
    } catch (e: any) {
      toast.error(e?.message || "否决失败")
    } finally {
      setRejectingId(null)
    }
  }, [fetchGroups])

  const filtered = groups.filter((g) => {
    const status = g.adjudication_status || "pending"
    if (filter === "all") return true
    return status === filter
  })

  const FILTER_TABS: { key: FilterTab; label: string }[] = [
    { key: "all", label: "全部" },
    { key: "pending", label: "待裁决" },
    { key: "accepted", label: "已采纳" },
    { key: "rejected", label: "已否决" },
  ]

  return (
    <div className="p-6 space-y-4">
      {/* 区域标题 */}
      <h1 className="text-xl font-bold tracking-tight">裁决面板</h1>
      <p className="text-sm text-muted-foreground -mt-2">
        AI 召回候选局限组，由你来判断哪些是真实信号、哪些不成立。
      </p>

      {/* 筛选 tabs */}
      <div className="flex gap-2">
        {FILTER_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setFilter(t.key)}
            className={cn(
              "px-3 py-1.5 text-sm rounded-md border transition-colors",
              filter === t.key
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background text-muted-foreground border-border hover:border-primary/50"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-muted-foreground py-8 text-center">加载中...</p>}

      {!loading && filtered.length === 0 && (
        <p className="text-sm text-muted-foreground py-8 text-center">无候选组数据</p>
      )}

      {/* 候选组列表 */}
      <div className="space-y-3">
        {filtered.map((cg) => {
          const status = cg.adjudication_status || "pending"
          return (
            <Card key={cg.id} className="hover:border-primary/30 transition-colors">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-4">
                  {/* 左: 信息区 */}
                  <div className="flex-1 min-w-0 space-y-1.5">
                    {/* group_label: 低权重, 小灰字 + 试探性口吻 */}
                    <p className="text-xs text-muted-foreground/70 italic">
                      AI 猜这组可能都关于:{" "}
                      <span className="not-italic">{cg.group_label}</span>
                    </p>

                    {/* 核心信息行 */}
                    <div className="flex items-center gap-2.5 flex-wrap">
                      {cg.topic && (
                        <Badge variant="outline" className="text-[0.65rem]">
                          {cg.topic}
                        </Badge>
                      )}
                      <span className="text-sm font-medium text-foreground">
                        {cg.claim_count} 条 claim
                      </span>
                      {formatCrossPaper(cg.cross_paper)}
                      <Badge variant={STATUS_BADGE[status]} className="text-[0.65rem]">
                        {STATUS_LABEL[status] || status}
                      </Badge>
                    </div>

                    {/* grouping_basis 辅助信息 */}
                    {cg.grouping_basis && (
                      <p className="text-xs text-muted-foreground line-clamp-1">
                        {cg.grouping_basis}
                      </p>
                    )}
                  </div>

                  {/* 右: 操作区 */}
                  <div className="flex items-center gap-2 shrink-0">
                    {(status === "pending") && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={rejectingId === cg.id}
                        onClick={() => handleQuickReject(cg)}
                        className="text-muted-foreground hover:text-destructive text-xs"
                      >
                        <X className="h-3.5 w-3.5" />
                        否决
                      </Button>
                    )}
                    {(status === "accepted" || status === "rejected") && (
                      <span className="text-xs text-muted-foreground">
                        {cg.signal_name ? `信号: ${cg.signal_name}` : ""}
                      </span>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onGoDetail(cg.id)}
                      className="text-xs"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      详判
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

// ============================================================================
// 视图二 · 单卡详判（裁决面板核心）
// ============================================================================

function DetailView({ groupId, onBack }: { groupId: string; onBack: () => void }) {
  const [detail, setDetail] = useState<CandidateGroupDetail | null>(null)
  const [signal, setSignal] = useState<SignalDetail | null>(null)
  const [loading, setLoading] = useState(true)

  // 裁决表单
  const [signalName, setSignalName] = useState("")
  const [rationale, setRationale] = useState("")

  // 弹窗
  const [acceptDialog, setAcceptDialog] = useState(false)
  const [editDialog, setEditDialog] = useState(false)
  const [editStatus, setEditStatus] = useState<string>("")
  const [editName, setEditName] = useState("")
  const [editRationale, setEditRationale] = useState("")

  // 操作中
  const [acting, setActing] = useState(false)

  const fetchDetail = useCallback(async () => {
    setLoading(true)
    try {
      // 获取候选组详情
      const d = await apiGet<CandidateGroupDetail>(`/adjudication/candidate-groups/${groupId}`)
      setDetail(d)

      // 检查是否已裁决: 从候选组列表缓存 signal_id
      // 先尝试获取关联的 signal
      const groups = await apiGet<CandidateGroup[]>(
        `/adjudication/candidate-groups`
      )
      const cg = groups.find((g) => g.id === groupId)
      const sigId = cg?.signal_id

      if (sigId) {
        const sd = await apiGet<SignalDetail>(`/adjudication/signals/${sigId}`)
        setSignal(sd)
        setSignalName(sd.signal_name || "")
        setRationale(sd.human_rationale || "")
      }
    } catch {
      toast.error("获取候选组详情失败")
    } finally {
      setLoading(false)
    }
  }, [groupId])

  useEffect(() => {
    fetchDetail()
  }, [fetchDetail])

  const isAdjudicated = !!signal

  // A1: 采纳并命名
  const handleAccept = useCallback(async () => {
    if (!signalName.trim()) {
      toast.error("采纳信号需要命名(signal_name)")
      return
    }
    setActing(true)
    try {
      const result = await apiPost<Signal>("/adjudication/signals", {
        action: "accept",
        candidate_group_id: groupId,
        signal_name: signalName.trim(),
        human_rationale: rationale.trim() || undefined,
      })
      setSignal({ ...result, claims: (detail?.claims || []).map((c) => ({ ...c, added_by: "adopted_from_group", added_at: new Date().toISOString() })) })
      setAcceptDialog(false)
      toast.success(`已采纳为信号: ${signalName.trim()}`)
    } catch (e: any) {
      toast.error(e?.message || "采纳失败")
    } finally {
      setActing(false)
    }
  }, [signalName, rationale, groupId, detail])

  // A2: 否决
  const handleReject = useCallback(async () => {
    setActing(true)
    try {
      const result = await apiPost<Signal>("/adjudication/signals", {
        action: "reject",
        candidate_group_id: groupId,
        human_rationale: rationale.trim() || undefined,
      })
      setSignal({ ...result, claims: [] })
      toast.success("已否决")
    } catch (e: any) {
      toast.error(e?.message || "否决失败")
    } finally {
      setActing(false)
    }
  }, [rationale, groupId])

  // A3: 踢出单条 claim
  const handleKickClaim = useCallback(async (claimId: string) => {
    if (!signal?.id) return
    setActing(true)
    try {
      await apiDelete(`/adjudication/signals/${signal.id}/claims/${claimId}`)
      toast.success("已踢出该 claim")
      // 刷新 signal
      const sd = await apiGet<SignalDetail>(`/adjudication/signals/${signal.id}`)
      setSignal(sd)
    } catch (e: any) {
      toast.error(e?.message || "踢出失败")
    } finally {
      setActing(false)
    }
  }, [signal?.id])

  // A6: 改裁决（打开编辑弹窗并预填当前值）
  const openEditDialog = useCallback(() => {
    if (!signal) return
    setEditStatus(signal.status)
    setEditName(signal.signal_name || "")
    setEditRationale(signal.human_rationale || "")
    setEditDialog(true)
  }, [signal])

  const handleEditSave = useCallback(async () => {
    if (!signal?.id) return
    setActing(true)
    try {
      const baseUrl = await resolveApiBase()
      const res = await fetch(`${baseUrl}/adjudication/signals/${signal.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signal_name: editName.trim() || undefined,
          status: editStatus || undefined,
          human_rationale: editRationale.trim() || undefined,
        }),
      })
      if (!res.ok) throw new Error(`PATCH failed: ${res.status}`)
      const updated = await res.json()

      setSignal({ ...updated, claims: signal.claims })
      setSignalName(updated.signal_name || "")
      setRationale(updated.human_rationale || "")
      setEditDialog(false)
      toast.success("裁决已更新")
    } catch (e: any) {
      toast.error(e?.message || "更新裁决失败")
    } finally {
      setActing(false)
    }
  }, [signal, editStatus, editName, editRationale])

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          返回
        </Button>
        <p className="text-sm text-muted-foreground py-8 text-center">加载中...</p>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="p-6 space-y-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          返回
        </Button>
        <p className="text-sm text-muted-foreground py-8 text-center">候选组未找到</p>
      </div>
    )
  }

  const claims = detail.claims || []
  const sigClaims = signal?.claims || []

  return (
    <div className="p-6 space-y-5 pb-32">
      {/* 顶部: 返回 + 候选组摘要(小字) */}
      <div>
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 mb-2">
          <ArrowLeft className="h-4 w-4" />
          返回列表
        </Button>

        {/* 摘要: 低权重 */}
        <div className="text-xs text-muted-foreground/70 space-y-0.5">
          <p className="italic">
            AI 猜这组可能都关于:{" "}
            <span className="not-italic text-muted-foreground">{detail.group_label}</span>
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            {detail.topic && (
              <Badge variant="outline" className="text-[0.65rem]">{detail.topic}</Badge>
            )}
            <span>{detail.claim_count} 条 claim</span>
            {formatCrossPaper(detail.cross_paper)}
            {detail.grouping_basis && (
              <span className="text-muted-foreground/60">· {detail.grouping_basis}</span>
            )}
          </div>
        </div>
      </div>

      {/* 已裁决的信号信息条 */}
      {isAdjudicated && (
        <div className={cn(
          "flex items-center gap-3 p-3 rounded-md border text-sm",
          signal.status === "accepted"
            ? "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/30 dark:border-emerald-800 dark:text-emerald-300"
            : signal.status === "rejected"
              ? "bg-red-50 border-red-200 text-red-800 dark:bg-red-950/30 dark:border-red-800 dark:text-red-300"
              : "bg-muted border-border"
        )}>
          <Badge variant={signal.status === "accepted" ? "default" : signal.status === "rejected" ? "destructive" : "secondary"}>
            {STATUS_LABEL[signal.status] || signal.status}
          </Badge>
          {signal.signal_name && (
            <span className="font-medium">{signal.signal_name}</span>
          )}
          {signal.human_rationale && (
            <span className="text-muted-foreground text-xs max-w-md truncate">
              备注: {signal.human_rationale}
            </span>
          )}
          <div className="flex-1" />
          <Button variant="ghost" size="sm" onClick={openEditDialog} className="text-xs">
            <Pencil className="h-3 w-3" />
            改裁决
          </Button>
        </div>
      )}

      {/* ── 主体: 每条 claim 一张卡 ── */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          判断依据
        </h2>

        {claims.length === 0 && (
          <p className="text-sm text-muted-foreground py-4">该候选组无 claim 数据</p>
        )}

        {claims.map((claim) => {
          const sc = sigClaims.find((s) => s.claim_id === claim.claim_id)
          const isKicked = sc?.added_by === "manual_remove"
          const quoteStatus = claim.quote_status || "unknown"

          return (
            <Card
              key={claim.claim_id}
              className={cn(
                "transition-all",
                isKicked && "opacity-45 grayscale"
              )}
            >
              <CardHeader className="pb-2">
                {/* 来源文献: 显眼位置, 第一行 */}
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base font-medium leading-snug">
                    {claim.paper_title || "未知文献"}
                  </CardTitle>
                  {/* 踢出按钮 (A3): 仅已采纳信号中活跃 claim 显示 */}
                  {signal?.status === "accepted" && !isKicked && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={acting}
                      onClick={() => handleKickClaim(claim.claim_id)}
                      className="shrink-0 text-xs text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950/30"
                    >
                      <X className="h-3 w-3" />
                      踢出
                    </Button>
                  )}
                  {isKicked && (
                    <Badge variant="destructive" className="shrink-0 text-[0.6rem]">
                      已踢出
                    </Badge>
                  )}
                </div>
              </CardHeader>

              <CardContent className="space-y-3">
                {/* quote 原文全文: 最大视觉块, 核心判断依据 */}
                <blockquote className={cn(
                  "border-l-3 pl-4 py-2 bg-muted/30 rounded-r text-sm leading-relaxed whitespace-pre-wrap break-words",
                  isKicked && "text-muted-foreground/60"
                )}>
                  {claim.quote || "（无原文）"}
                </blockquote>

                {/* 引文元数据行 */}
                <div className="flex items-center gap-2 flex-wrap text-xs">
                  {/* quote_status: 诚实标记, 必须显著 */}
                  {quoteStatus === "unverified" ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300 font-medium border border-amber-200 dark:border-amber-800">
                      <AlertTriangle className="h-3 w-3" />
                      模型原话 · 未逐字定位
                    </span>
                  ) : quoteStatus === "verified" ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300 font-medium border border-emerald-200 dark:border-emerald-800">
                      <Check className="h-3 w-3" />
                      已逐字定位
                    </span>
                  ) : (
                    <span className="text-muted-foreground/50">
                      定位状态未知
                    </span>
                  )}

                  {/* 页码 */}
                  {claim.quote_page != null && (
                    <span className="text-muted-foreground">
                      p.{claim.quote_page}
                    </span>
                  )}
                </div>

                {/* 标签行: topic + claim_form + context(降级为模型标签) */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  {claim.topic && (
                    <Badge variant="outline" className="text-[0.6rem]">
                      {claim.topic}
                    </Badge>
                  )}
                  {claim.claim_form && (
                    <Badge variant="secondary" className="text-[0.6rem]">
                      {claim.claim_form}
                    </Badge>
                  )}
                  {claim.context_summary && (
                    <span className="text-[0.65rem] text-muted-foreground/60">
                      模型: {claim.context_summary}
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* ── 底部裁决操作区 (sticky, 未裁决时显示) ── */}
      {!isAdjudicated && (
        <div className="fixed bottom-0 left-60 right-0 bg-background border-t border-border p-4 z-40 shadow-lg">
          <div className="max-w-3xl mx-auto space-y-3">
            <Input
              placeholder="signal_name: 为这个信号命名（采纳前必须填写）"
              value={signalName}
              onChange={(e) => setSignalName(e.target.value)}
              className="text-sm"
            />
            <div className="flex gap-3">
              <Input
                placeholder="备注/判断理由（可选）"
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                className="text-sm flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                disabled={acting}
                onClick={handleReject}
                className="shrink-0 text-xs"
              >
                <X className="h-3.5 w-3.5" />
                否决
              </Button>
              <Button
                size="sm"
                disabled={acting || !signalName.trim()}
                onClick={() => setAcceptDialog(true)}
                className="shrink-0 text-xs"
              >
                <Check className="h-3.5 w-3.5" />
                采纳
              </Button>
            </div>
            <p className="text-[0.65rem] text-muted-foreground/60">
              请先逐条看清上方的来源文献、原文引用和定位状态，再做裁决。AI 只负责分组，不下结论。
            </p>
          </div>
        </div>
      )}

      {/* 采纳确认弹窗 */}
      <Dialog open={acceptDialog} onOpenChange={setAcceptDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认采纳</DialogTitle>
            <DialogDescription>
              将此候选组采纳为确认信号，命名后不能再通过列表快速否决。
              你填写的 signal_name 和备注将作为信号的正式标识。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="text-xs font-medium text-muted-foreground">信号名称</label>
              <p className="text-sm font-medium mt-0.5">{signalName}</p>
            </div>
            {rationale && (
              <div>
                <label className="text-xs font-medium text-muted-foreground">备注</label>
                <p className="text-sm text-muted-foreground mt-0.5">{rationale}</p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setAcceptDialog(false)}>
              取消
            </Button>
            <Button size="sm" disabled={acting} onClick={handleAccept}>
              <Check className="h-3.5 w-3.5" />
              确认采纳
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 改裁决弹窗 (A6) */}
      <Dialog open={editDialog} onOpenChange={setEditDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>修改裁决</DialogTitle>
            <DialogDescription>
              可修改信号名称、裁决状态或备注。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="text-xs font-medium text-muted-foreground">信号名称</label>
              <Input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="mt-1"
                placeholder="signal_name"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">裁决状态</label>
              <div className="flex gap-2 mt-1">
                {["pending", "accepted", "rejected"].map((s) => (
                  <button
                    key={s}
                    onClick={() => setEditStatus(s)}
                    className={cn(
                      "px-3 py-1.5 text-xs rounded-md border transition-colors",
                      editStatus === s
                        ? s === "accepted"
                          ? "bg-emerald-100 border-emerald-400 text-emerald-800 dark:bg-emerald-950/50 dark:border-emerald-600 dark:text-emerald-300"
                          : s === "rejected"
                            ? "bg-red-100 border-red-400 text-red-800 dark:bg-red-950/50 dark:border-red-600 dark:text-red-300"
                            : "bg-amber-100 border-amber-400 text-amber-800 dark:bg-amber-950/50 dark:border-amber-600 dark:text-amber-300"
                        : "bg-background text-muted-foreground border-border hover:border-primary/50"
                    )}
                  >
                    {STATUS_LABEL[s]}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">备注</label>
              <Input
                value={editRationale}
                onChange={(e) => setEditRationale(e.target.value)}
                className="mt-1"
                placeholder="判断理由"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditDialog(false)}>
              取消
            </Button>
            <Button size="sm" disabled={acting} onClick={handleEditSave}>
              保存修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
