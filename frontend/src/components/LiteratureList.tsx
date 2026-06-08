import { useState, useEffect, useCallback } from "react"
import {
  Search,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Loader2,
  FileSearch,
  ArrowUpDown,
} from "lucide-react"
import { cn } from "../lib/utils"
import { apiGet } from "../api/client"
import type { PaperListItem, PaperListResponse, PaperStatus } from "../types"

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
}

// ============================================================================
// LiteratureList 组件
// ============================================================================

export default function LiteratureList({ refreshKey = 0 }: LiteratureListProps) {
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

  // ── 多选 ──
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // ── 数据获取 ──

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
  }, [page, pageSize, search, statusFilter, sort, yearFilter])

  // 首次加载 & 参数变化 & 外部刷新时重新获取
  useEffect(() => {
    fetchPapers()
  }, [fetchPapers, refreshKey])

  // 搜索防抖：300ms 后执行
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  // ── 分页计算 ──

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const hasPrev = page > 1
  const hasNext = page < totalPages

  // ── 多选操作 ──

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    if (selectedIds.size === papers.length && papers.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(papers.map((p) => p.id)))
    }
  }, [papers, selectedIds.size])

  // ── 标题截断 ──

  const truncateTitle = (title: string | null, max = 80): string => {
    if (!title) return "（无标题）"
    return title.length > max ? title.slice(0, max) + "…" : title
  }

  return (
    <div className="space-y-3">
      {/* ── 搜索栏 + 操作区 ── */}
      <div className="flex flex-wrap items-center gap-2">
        {/* 搜索框 */}
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

        {/* 状态筛选 */}
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring"
        >
          {STATUS_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {/* 年份筛选 */}
        <input
          type="number"
          value={yearFilter}
          onChange={(e) => { setYearFilter(e.target.value); setPage(1) }}
          placeholder="年份"
          className="w-24 rounded-md border border-input bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
        />

        {/* 排序 */}
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value); setPage(1) }}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {/* 排序图标 */}
        <ArrowUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </div>

      {/* ── 多选信息条 ── */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-2 rounded-md bg-primary/10 px-3 py-1.5 text-sm text-primary">
          已选中 {selectedIds.size} 篇文献
        </div>
      )}

      {/* ── 加载 / 错误 / 空状态 ── */}
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

      {/* ── 文献表格 ── */}
      {!loading && !error && papers.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left">
                  <th className="w-10 px-3 py-2.5">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === papers.length && papers.length > 0}
                      onChange={toggleSelectAll}
                      className="h-4 w-4 rounded border-input"
                    />
                  </th>
                  <th className="px-3 py-2.5 font-medium text-muted-foreground">标题</th>
                  <th className="hidden px-3 py-2.5 font-medium text-muted-foreground md:table-cell">作者</th>
                  <th className="hidden w-16 px-3 py-2.5 font-medium text-muted-foreground sm:table-cell">年份</th>
                  <th className="hidden w-24 px-3 py-2.5 font-medium text-muted-foreground lg:table-cell">期刊</th>
                  <th className="w-24 px-3 py-2.5 font-medium text-muted-foreground">状态</th>
                  <th className="hidden w-32 px-3 py-2.5 font-medium text-muted-foreground xl:table-cell">标签</th>
                </tr>
              </thead>
              <tbody>
                {papers.map((paper) => (
                  <tr
                    key={paper.id}
                    className={cn(
                      "border-b border-border transition-colors hover:bg-muted/30",
                      selectedIds.has(paper.id) && "bg-primary/5"
                    )}
                  >
                    {/* 复选框 */}
                    <td className="px-3 py-2.5">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(paper.id)}
                        onChange={() => toggleSelect(paper.id)}
                        className="h-4 w-4 rounded border-input"
                      />
                    </td>

                    {/* 标题 */}
                    <td className="max-w-[300px] px-3 py-2.5">
                      <span className="line-clamp-2 font-medium" title={paper.title ?? undefined}>
                        {truncateTitle(paper.title)}
                      </span>
                    </td>

                    {/* 作者 */}
                    <td className="hidden px-3 py-2.5 text-muted-foreground md:table-cell">
                      {paper.authors && paper.authors.length > 0
                        ? paper.authors[0] + (paper.authors.length > 1 ? ` +${paper.authors.length - 1}` : "")
                        : "—"}
                    </td>

                    {/* 年份 */}
                    <td className="hidden px-3 py-2.5 text-muted-foreground sm:table-cell">
                      {paper.year ?? "—"}
                    </td>

                    {/* 期刊 */}
                    <td className="hidden max-w-[160px] px-3 py-2.5 text-muted-foreground lg:table-cell">
                      <span className="line-clamp-1">{paper.journal ?? "—"}</span>
                    </td>

                    {/* 状态 Badge */}
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

                    {/* 标签 */}
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ── 分页 ── */}
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

              {/* 页码 */}
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
    </div>
  )
}

// 导出当前选中 ID 的 getter（通过 ref 模式，父组件可用）
export type { LiteratureListProps }
