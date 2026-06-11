import { useState, useEffect, useCallback, useRef } from "react"
import {
  Search,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Loader2,
  FileSearch,
  ArrowUpDown,
  MessageSquare,
  X,
  MoreVertical,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"
import { cn } from "../lib/utils"
import { apiGet, apiDelete, apiPost } from "../api/client"
import { Button } from "./ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "./ui/dialog"
import type {
  PaperListItem,
  PaperListResponse,
  PaperStatus,
  Project,
  BatchDeleteRequest,
  BatchDeleteResponse,
} from "../types"

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

const SORT_OPTIONS = [
  { value: "", label: "默认排序" },
  { value: "year", label: "按年份" },
  { value: "time", label: "按时间" },
  { value: "title", label: "按标题" },
]

const STATUS_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "待处理" },
  { value: "extracting", label: "提取中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "extract_failed", label: "提取失败" },
]

// ============================================================================
// Props
// ============================================================================

interface LiteratureListProps {
  /** 外部触发的刷新信号（递增触发 re-fetch） */
  refreshKey?: number
  /** 受控模式：外部传入选中 ID 集合 */
  selectedIds?: string[]
  /** 选择变化回调，用于暴露给父组件（M11 跨文献问答接入） */
  onSelectionChange?: (ids: string[]) => void
  /** 点击文献行回调（打开详情） */
  onSelectPaper?: (paperId: string) => void
  /** 跨文献问答回调（多选后触发） */
  onChatMulti?: (paperIds: string[]) => void
  /** 项目列表（用于筛选下拉） */
  projects?: Project[]
  /** 受控：当前项目筛选 ID（空字符串表示全部） */
  projectFilter?: string
  /** 项目筛选变化回调 */
  onProjectFilterChange?: (projectId: string) => void
  /** 删除成功后回调（刷新计数等） */
  onDeleted?: () => void
}

// ============================================================================
// LiteratureList 组件
// ============================================================================

export default function LiteratureList({
  refreshKey = 0,
  selectedIds: externalSelectedIds,
  onSelectionChange,
  onSelectPaper,
  onChatMulti,
  projects,
  projectFilter = "",
  onProjectFilterChange,
  onDeleted,
}: LiteratureListProps) {
  // ── 数据状态 ──
  const [papers, setPapers] = useState<PaperListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── 筛选 / 排序 / 分页状态 ──
  const [search, setSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [yearFilter, setYearFilter] = useState("")
  const [sort, setSort] = useState("")
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)

  // ── 删除 ──
  const [deleteTarget, setDeleteTarget] = useState<PaperListItem | null>(null)
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // ── 行菜单 ──
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  // ── 多选 ──
  const isControlled = externalSelectedIds !== undefined
  const [internalSelectedIds, setInternalSelectedIds] = useState<Set<string>>(new Set())

  const selectedSet = isControlled
    ? new Set(externalSelectedIds)
    : internalSelectedIds

  const notifySelection = useCallback(
    (ids: Set<string>) => {
      onSelectionChange?.(Array.from(ids))
    },
    [onSelectionChange]
  )

  const updateSelection = useCallback(
    (updater: (prev: Set<string>) => Set<string>) => {
      if (isControlled) {
        const current = new Set(externalSelectedIds)
        const next = updater(current)
        onSelectionChange?.(Array.from(next))
      } else {
        setInternalSelectedIds((prev) => {
          const next = updater(prev)
          setTimeout(() => notifySelection(next), 0)
          return next
        })
      }
    },
    [isControlled, externalSelectedIds, onSelectionChange, notifySelection]
  )

  useEffect(() => {
    if (isControlled) {
      onSelectionChange?.([])
    } else {
      setInternalSelectedIds(new Set())
      notifySelection(new Set())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  // 点击外部关闭行菜单
  useEffect(() => {
    if (!menuOpenId) return
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [menuOpenId])

  const fetchPapers = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const params = new URLSearchParams()
      params.set("page", String(page))
      params.set("page_size", String(pageSize))
      if (search) params.set("search", search)
      if (statusFilter) params.set("status", statusFilter)
      if (sort) params.set("sort", sort)
      if (yearFilter) params.set("year", yearFilter)
      if (projectFilter) params.set("project_id", projectFilter)

      const res = await apiGet<PaperListResponse>(
        `/literature/?${params.toString()}`
      )
      setPapers(res.items)
      setTotal(res.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载文献列表失败")
      setPapers([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search, statusFilter, sort, yearFilter, projectFilter])

  useEffect(() => {
    fetchPapers()
  }, [fetchPapers, refreshKey])

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  // 项目筛选变化时回到第一页
  useEffect(() => {
    setPage(1)
  }, [projectFilter])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const hasPrev = page > 1
  const hasNext = page < totalPages

  const toggleSelect = useCallback(
    (id: string) => {
      updateSelection((prev) => {
        const next = new Set(prev)
        if (next.has(id)) { next.delete(id) } else { next.add(id) }
        return next
      })
    },
    [updateSelection]
  )

  const toggleSelectAll = useCallback(() => {
    const currentIds = papers.map((p) => p.id)
    const allSelected = currentIds.every((id) => selectedSet.has(id))
    if (allSelected && currentIds.length > 0) {
      updateSelection((prev) => {
        const next = new Set(prev)
        currentIds.forEach((id) => next.delete(id))
        return next
      })
    } else {
      updateSelection(() => new Set(currentIds))
    }
  }, [papers, selectedSet, updateSelection])

  const clearSelection = useCallback(() => {
    updateSelection(() => new Set())
  }, [updateSelection])

  const handleDeleteSingle = useCallback(async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await apiDelete(`/literature/${deleteTarget.id}`)
      toast.success("文献已删除")
      setDeleteTarget(null)
      clearSelection()
      await fetchPapers()
      onDeleted?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeleting(false)
    }
  }, [deleteTarget, clearSelection, fetchPapers, onDeleted])

  const handleDeleteBatch = useCallback(async () => {
    const ids = Array.from(selectedSet)
    if (ids.length === 0) return
    setDeleting(true)
    try {
      const body: BatchDeleteRequest = { paper_ids: ids }
      const res = await apiPost<BatchDeleteResponse>("/literature/batch-delete", body)
      toast.success(`已删除 ${res.deleted_count} 篇文献`)
      setBatchDeleteOpen(false)
      clearSelection()
      await fetchPapers()
      onDeleted?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "批量删除失败")
    } finally {
      setDeleting(false)
    }
  }, [selectedSet, clearSelection, fetchPapers, onDeleted])

  const truncateTitle = (title: string | null, max = 80): string => {
    if (!title) return "（无标题）"
    return title.length > max ? title.slice(0, max) + "…" : title
  }

  const selectedCount = selectedSet.size

  return (
    <div className="space-y-3">
      {/* ── 搜索栏 + 操作区 ── */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="全文搜索文献…"
            className="w-full rounded-md border border-input bg-background py-2 pl-9 pr-3 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
          />
        </div>

        {projects && projects.length > 0 && (
          <select
            value={projectFilter}
            onChange={(e) => onProjectFilterChange?.(e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring"
          >
            <option value="">全部项目</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.paper_count})
              </option>
            ))}
          </select>
        )}

        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring"
        >
          {STATUS_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <input
          type="number"
          value={yearFilter}
          onChange={(e) => { setYearFilter(e.target.value); setPage(1) }}
          placeholder="年份"
          className="w-24 rounded-md border border-input bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
        />

        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value); setPage(1) }}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <ArrowUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </div>

      {/* ── 多选操作条 ── */}
      {selectedCount > 0 && (
        <div className="flex items-center gap-2 rounded-md bg-primary/10 px-3 py-1.5 text-sm">
          <span className="text-primary">
            已选中 {selectedCount} 篇文献
          </span>
          <button
            onClick={clearSelection}
            className="ml-1 rounded p-0.5 text-primary/60 hover:text-primary transition-colors"
            title="清空选择"
          >
            <X className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setBatchDeleteOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-destructive/30 px-3 py-1 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
            删除选中
          </button>
          <button
            onClick={() => onChatMulti?.(Array.from(selectedSet))}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            跨文献问答
          </button>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">加载中…</span>
        </div>
      )}

      {error && !loading && (
        <div className="flex items-center justify-center py-16">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      {!loading && !error && papers.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <FileSearch className="mb-3 h-10 w-10 opacity-40" />
          <p className="text-sm">暂无文献</p>
          <p className="mt-1 text-xs opacity-60">上传 PDF 文件开始构建文献库</p>
        </div>
      )}

      {!loading && !error && papers.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left">
                  <th className="w-10 px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={papers.length > 0 && papers.every((p) => selectedSet.has(p.id))}
                      onChange={toggleSelectAll}
                      title="全选本页"
                      className="h-4 w-4 rounded border-input"
                    />
                  </th>
                  <th className="px-3 py-2.5 font-medium text-muted-foreground">标题</th>
                  <th className="hidden w-28 px-3 py-2.5 font-medium text-muted-foreground md:table-cell">项目</th>
                  <th className="hidden px-3 py-2.5 font-medium text-muted-foreground md:table-cell">作者</th>
                  <th className="hidden w-16 px-3 py-2.5 font-medium text-muted-foreground sm:table-cell">年份</th>
                  <th className="hidden w-24 px-3 py-2.5 font-medium text-muted-foreground lg:table-cell">期刊</th>
                  <th className="w-24 px-3 py-2.5 font-medium text-muted-foreground">状态</th>
                  <th className="hidden w-32 px-3 py-2.5 font-medium text-muted-foreground xl:table-cell">标签</th>
                  <th className="w-10 px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {papers.map((paper) => (
                  <tr
                    key={paper.id}
                    onClick={() => onSelectPaper?.(paper.id)}
                    className={cn(
                      "border-b border-border transition-colors hover:bg-muted/30 cursor-pointer",
                      selectedSet.has(paper.id) && "bg-primary/5"
                    )}
                  >
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedSet.has(paper.id)}
                        onChange={() => toggleSelect(paper.id)}
                        className="h-4 w-4 rounded border-input"
                      />
                    </td>
                    <td className="max-w-[300px] px-3 py-2.5">
                      <span className="line-clamp-2 font-medium" title={paper.title ?? undefined}>
                        {truncateTitle(paper.title)}
                      </span>
                    </td>
                    <td className="hidden px-3 py-2.5 text-muted-foreground md:table-cell">
                      <span className="line-clamp-1 text-xs">
                        {paper.project_name ?? "未分类"}
                      </span>
                    </td>
                    <td className="hidden px-3 py-2.5 text-muted-foreground md:table-cell">
                      {paper.authors && paper.authors.length > 0
                        ? paper.authors[0] + (paper.authors.length > 1 ? ` +${paper.authors.length - 1}` : "")
                        : "—"}
                    </td>
                    <td className="hidden px-3 py-2.5 text-muted-foreground sm:table-cell">
                      {paper.year ?? "—"}
                    </td>
                    <td className="hidden max-w-[160px] px-3 py-2.5 text-muted-foreground lg:table-cell">
                      <span className="line-clamp-1">{paper.journal ?? "—"}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={cn(
                          "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                          STATUS_MAP[paper.status]?.className ?? "bg-muted text-muted-foreground"
                        )}
                      >
                        {STATUS_MAP[paper.status]?.label ?? paper.status}
                      </span>
                    </td>
                    <td className="hidden px-3 py-2.5 xl:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {paper.tags.length > 0 ? (
                          paper.tags.slice(0, 3).map((tag) => (
                            <span
                              key={tag}
                              className="inline-block rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                            >
                              {tag}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-muted-foreground/50">—</span>
                        )}
                        {paper.tags.length > 3 && (
                          <span className="text-xs text-muted-foreground">+{paper.tags.length - 3}</span>
                        )}
                      </div>
                    </td>
                    <td className="relative px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => setMenuOpenId(menuOpenId === paper.id ? null : paper.id)}
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                        title="更多操作"
                      >
                        <MoreVertical className="h-4 w-4" />
                      </button>
                      {menuOpenId === paper.id && (
                        <div
                          ref={menuRef}
                          className="absolute right-2 top-full z-10 mt-1 min-w-[120px] rounded-md border border-border bg-popover py-1 shadow-md"
                        >
                          <button
                            onClick={() => {
                              setMenuOpenId(null)
                              setDeleteTarget(paper)
                            }}
                            className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            删除
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              共 {total} 篇 · 第 {page}/{totalPages} 页
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(1)}
                disabled={!hasPrev}
                className={cn(
                  "rounded p-1.5 transition-colors",
                  hasPrev
                    ? "text-muted-foreground hover:text-foreground"
                    : "pointer-events-none text-muted-foreground/30"
                )}
              >
                <ChevronsLeft className="h-4 w-4" />
              </button>
              <button
                onClick={() => setPage((p) => p - 1)}
                disabled={!hasPrev}
                className={cn(
                  "rounded p-1.5 transition-colors",
                  hasPrev
                    ? "text-muted-foreground hover:text-foreground"
                    : "pointer-events-none text-muted-foreground/30"
                )}
              >
                <ChevronLeft className="h-4 w-4" />
              </button>

              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum: number
                if (totalPages <= 5) {
                  pageNum = i + 1
                } else if (page <= 3) {
                  pageNum = i + 1
                } else if (page >= totalPages - 2) {
                  pageNum = totalPages - 4 + i
                } else {
                  pageNum = page - 2 + i
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    className={cn(
                      "min-w-[2rem] rounded px-2 py-1 text-center transition-colors",
                      pageNum === page
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted"
                    )}
                  >
                    {pageNum}
                  </button>
                )
              })}

              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={!hasNext}
                className={cn(
                  "rounded p-1.5 transition-colors",
                  hasNext
                    ? "text-muted-foreground hover:text-foreground"
                    : "pointer-events-none text-muted-foreground/30"
                )}
              >
                <ChevronRight className="h-4 w-4" />
              </button>
              <button
                onClick={() => setPage(totalPages)}
                disabled={!hasNext}
                className={cn(
                  "rounded p-1.5 transition-colors",
                  hasNext
                    ? "text-muted-foreground hover:text-foreground"
                    : "pointer-events-none text-muted-foreground/30"
                )}
              >
                <ChevronsRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── 单篇删除确认 ── */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent onClose={() => setDeleteTarget(null)} className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确定删除？</DialogTitle>
            <DialogDescription>
              将永久删除「{truncateTitle(deleteTarget?.title ?? null, 40)}」，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleDeleteSingle} disabled={deleting}>
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 批量删除确认 ── */}
      <Dialog open={batchDeleteOpen} onOpenChange={setBatchDeleteOpen}>
        <DialogContent onClose={() => setBatchDeleteOpen(false)} className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确定删除？</DialogTitle>
            <DialogDescription>
              将永久删除选中的 {selectedCount} 篇文献，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBatchDeleteOpen(false)} disabled={deleting}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleDeleteBatch} disabled={deleting}>
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export type { LiteratureListProps }
