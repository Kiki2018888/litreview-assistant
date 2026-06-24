import { useState, useCallback, useRef, useEffect } from "react"
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Maximize, AlertTriangle, Loader2 } from "lucide-react"
import { cn } from "../lib/utils"
import { resolveApiBase } from "../api/client"

// ============================================================================
// Props
// ============================================================================

interface PdfViewerProps {
  /** PDF 文件的绝对路径（用于构造 file:// URL，作为 fallback） */
  filePath: string | null
  /** PDF 总页数 */
  pageCount?: number | null
  /** 文献 ID，优先通过后端 API 获取 PDF 二进制（解决 Electron webSecurity 拦截 file:// 的问题） */
  paperId?: string | null
}

// ============================================================================
// PdfViewer 组件
// ============================================================================

export default function PdfViewer({ filePath, pageCount, paperId }: PdfViewerProps) {
  const [zoom, setZoom] = useState(100)
  const [currentPage, setCurrentPage] = useState(1)
  const [pdfError, setPdfError] = useState(false)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loadingPdf, setLoadingPdf] = useState(false)
  const blobUrlRef = useRef<string | null>(null)

  const totalPages = pageCount && pageCount > 0 ? pageCount : 1

  // ── 通过后端 API 获取 PDF 二进制，生成 blob URL ──
  useEffect(() => {
    let cancelled = false

    const fetchPdf = async () => {
      setLoadingPdf(true)
      setPdfError(false)
      setBlobUrl(null)

      // 释放旧的 blob URL
      if (blobUrlRef.current?.startsWith("blob:")) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }

      try {
        if (!paperId) {
          // 无 paperId：回退到 file://（仅浏览器 dev 模式可能可用）
          if (filePath) {
            const url = `file:///${filePath.replace(/\\/g, "/")}`
            blobUrlRef.current = url
            if (!cancelled) setBlobUrl(url)
          } else {
            if (!cancelled) setPdfError(true)
          }
          return
        }

        const base = await resolveApiBase()
        const res = await fetch(`${base}/literature/${paperId}/file`)

        if (!res.ok) {
          // HTTP 错误：回退 file://
          if (filePath) {
            const url = `file:///${filePath.replace(/\\/g, "/")}`
            blobUrlRef.current = url
            if (!cancelled) setBlobUrl(url)
          } else {
            if (!cancelled) setPdfError(true)
          }
          return
        }

        const blob = await res.blob()
        if (cancelled) return

        const url = URL.createObjectURL(blob)
        blobUrlRef.current = url
        setBlobUrl(url)
      } catch {
        // 网络错误 / AbortError：回退 file://
        if (cancelled) return
        if (filePath) {
          const url = `file:///${filePath.replace(/\\/g, "/")}`
          blobUrlRef.current = url
          setBlobUrl(url)
        } else {
          setPdfError(true)
        }
      } finally {
        if (!cancelled) setLoadingPdf(false)
      }
    }

    fetchPdf()

    return () => {
      cancelled = true
    }
  }, [paperId, filePath])

  // 组件卸载时释放 blob URL
  useEffect(() => {
    return () => {
      if (blobUrlRef.current?.startsWith("blob:")) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }
    }
  }, [])

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

  // ── 无文件路径 ──
  if (!filePath && !paperId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <AlertTriangle className="h-10 w-10 mb-3 opacity-40" />
        <p className="text-sm">无法加载 PDF</p>
        <p className="text-xs mt-1 opacity-60">缺少文件路径信息</p>
      </div>
    )
  }

  // ── 正在加载 PDF ──
  if (loadingPdf) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <Loader2 className="h-8 w-8 mb-3 animate-spin opacity-40" />
        <p className="text-sm">正在加载 PDF…</p>
      </div>
    )
  }

  // 最终使用的 PDF URL
  const pdfUrl = blobUrl
  const pdfSrc = pdfUrl ? `${pdfUrl}#page=${currentPage}&zoom=${zoom}` : null

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

      {/* ── PDF 预览区（embed 在 Electron 下可渲染 blob PDF，iframe sandbox 不行） ── */}
      <div className="flex-1 relative bg-[#525659] dark:bg-[#1e1e1e]">
        {pdfError || !pdfSrc ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground">
            <AlertTriangle className="h-10 w-10 mb-3 opacity-40" />
            <p className="text-sm">PDF 预览不可用</p>
            <p className="text-xs mt-1 opacity-60 max-w-[280px] text-center">
              无法加载 PDF 文件。请确保后端文件服务已启动。
            </p>
          </div>
        ) : (
          <embed
            type="application/pdf"
            src={pdfSrc}
            className="absolute inset-0 h-full w-full border-0"
            title="PDF Preview"
          />
        )}
      </div>
    </div>
  )
}
