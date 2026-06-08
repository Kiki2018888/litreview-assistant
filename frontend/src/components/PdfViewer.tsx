import { useState, useCallback, useRef } from "react"
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Maximize, AlertTriangle } from "lucide-react"
import { cn } from "../lib/utils"

// ============================================================================
// Props
// ============================================================================

interface PdfViewerProps {
  /** PDF 文件的绝对路径（用于构造 file:// URL） */
  filePath: string | null
  /** PDF 总页数 */
  pageCount?: number | null
}

// ============================================================================
// PdfViewer 组件
// ============================================================================

export default function PdfViewer({ filePath, pageCount }: PdfViewerProps) {
  const [zoom, setZoom] = useState(100)
  const [currentPage, setCurrentPage] = useState(1)
  const [iframeError, setIframeError] = useState(false)
  const iframeRef = useRef<HTMLIFrameElement>(null)

  const totalPages = pageCount && pageCount > 0 ? pageCount : 1

  // 构造 PDF URL：Electron 使用 file:// 协议
  const pdfUrl = filePath
    ? `file:///${filePath.replace(/\\/g, "/")}`
    : null

  // ── 缩放控制 ──

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min(z + 25, 300))
  }, [])

  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max(z - 25, 25))
  }, [])

  const fitWidth = useCallback(() => {
    setZoom(100)
  }, [])

  // ── 页码导航 ──

  const goToPage = useCallback(
    (page: number) => {
      const clamped = Math.max(1, Math.min(page, totalPages))
      setCurrentPage(clamped)
    },
    [totalPages]
  )

  const prevPage = useCallback(() => goToPage(currentPage - 1), [currentPage, goToPage])
  const nextPage = useCallback(() => goToPage(currentPage + 1), [currentPage, goToPage])

  const handlePageInput = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        const val = parseInt((e.target as HTMLInputElement).value, 10)
        if (!isNaN(val)) goToPage(val)
      }
    },
    [goToPage]
  )

  // ── iframe 加载错误处理 ──

  const handleIframeError = useCallback(() => {
    setIframeError(true)
  }, [])

  // ── 无文件路径 ──

  if (!pdfUrl) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <AlertTriangle className="h-10 w-10 mb-3 opacity-40" />
        <p className="text-sm">无法加载 PDF</p>
        <p className="text-xs mt-1 opacity-60">缺少文件路径信息</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* ── 工具栏 ── */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2 bg-muted/30 shrink-0">
        {/* 页码导航 */}
        <div className="flex items-center gap-1 text-sm">
          <button
            onClick={prevPage}
            disabled={currentPage <= 1}
            className={cn(
              "rounded p-1 transition-colors",
              currentPage > 1
                ? "text-muted-foreground hover:text-foreground"
                : "text-muted-foreground/30 pointer-events-none"
            )}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>

          <span className="flex items-center gap-1 min-w-[80px] justify-center text-muted-foreground">
            <input
              type="number"
              value={currentPage}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10)
                if (!isNaN(v)) setCurrentPage(v)
              }}
              onKeyDown={handlePageInput}
              min={1}
              max={totalPages}
              className="w-10 text-center rounded border border-input bg-background px-1 py-0.5 text-sm outline-none focus:border-ring"
            />
            <span>/ {totalPages}</span>
          </span>

          <button
            onClick={nextPage}
            disabled={currentPage >= totalPages}
            className={cn(
              "rounded p-1 transition-colors",
              currentPage < totalPages
                ? "text-muted-foreground hover:text-foreground"
                : "text-muted-foreground/30 pointer-events-none"
            )}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        {/* 缩放控制 */}
        <div className="flex items-center gap-1">
          <button
            onClick={zoomOut}
            disabled={zoom <= 25}
            className="rounded p-1 text-muted-foreground hover:text-foreground transition-colors"
            title="缩小"
          >
            <ZoomOut className="h-4 w-4" />
          </button>

          <button
            onClick={fitWidth}
            className="rounded px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            title="适应宽度"
          >
            <Maximize className="h-3.5 w-3.5" />
          </button>

          <span className="text-xs text-muted-foreground min-w-[3rem] text-center tabular-nums">
            {zoom}%
          </span>

          <button
            onClick={zoomIn}
            disabled={zoom >= 300}
            className="rounded p-1 text-muted-foreground hover:text-foreground transition-colors"
            title="放大"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* ── PDF 预览区 ── */}
      <div className="flex-1 relative bg-[#525659] dark:bg-[#1e1e1e]">
        {iframeError ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground">
            <AlertTriangle className="h-10 w-10 mb-3 opacity-40" />
            <p className="text-sm">PDF 预览不可用</p>
            <p className="text-xs mt-1 opacity-60 max-w-[280px] text-center">
              浏览器安全策略阻止了 file:// 协议加载。
              请使用 Electron 应用查看 PDF。
            </p>
          </div>
        ) : (
          <iframe
            ref={iframeRef}
            src={`${pdfUrl}#page=${currentPage}&zoom=${zoom}`}
            className="w-full h-full border-0"
            onError={handleIframeError}
            title="PDF Preview"
            sandbox="allow-scripts allow-same-origin"
          />
        )}
      </div>
    </div>
  )
}
