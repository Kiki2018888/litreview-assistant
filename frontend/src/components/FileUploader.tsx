import { useState, useRef, useCallback, useEffect } from "react"
import { Upload, X, FileText, Check, AlertCircle, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { cn } from "../lib/utils"
import { apiUpload } from "../api/client"
import type { PaperUploadResponse, Batch } from "../types"

// ============================================================================
// 常量
// ============================================================================

const MAX_FILES = 50
const MAX_SIZE_MB = 50
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

// ============================================================================
// Props
// ============================================================================

interface FileUploaderProps {
  /** 上传成功后回调，用于刷新列表 */
  onUploadComplete?: () => void
  /** 可选批次列表（下拉选择） */
  batches?: Batch[]
}

// ============================================================================
// 上传条目状态
// ============================================================================

interface UploadItem {
  file: File
  status: "pending" | "uploading" | "done" | "error"
  error?: string
  paperId?: string
}

// ============================================================================
// FileUploader 组件
// ============================================================================

export default function FileUploader({ onUploadComplete, batches }: FileUploaderProps) {
  const [items, setItems] = useState<UploadItem[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [batchId, setBatchId] = useState<string>("")
  const fileInputRef = useRef<HTMLInputElement>(null)

  // AbortController ref：组件卸载时取消进行中的上传
  const abortRef = useRef<AbortController | null>(null)

  // 组件卸载清理
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  // ── 文件校验 ──

  const validateFiles = useCallback((files: FileList | File[]): { valid: File[]; rejected: string[] } => {
    const rejected: string[] = []
    const valid: File[] = []

    const remaining = MAX_FILES - items.length
    if (remaining <= 0) {
      rejected.push(`队列已满（最多 ${MAX_FILES} 个），无法继续添加`)
      return { valid, rejected }
    }

    // 按目录顺序截断，确保不超过 MAX_FILES
    let added = 0
    for (const f of files) {
      if (!f.name.toLowerCase().endsWith(".pdf")) {
        rejected.push(`"${f.name}" 不是 PDF 文件`)
        continue
      }
      if (f.size > MAX_SIZE_BYTES) {
        rejected.push(`"${f.name}" 超过 ${MAX_SIZE_MB}MB 限制`)
        continue
      }
      if (added >= remaining) {
        rejected.push(`已达到上限 ${MAX_FILES} 个，"${f.name}" 未添加`)
        continue
      }
      valid.push(f)
      added++
    }

    return { valid, rejected }
  }, [items.length])

  // ── 添加文件 ──

  const addFiles = useCallback((files: File[]) => {
    const { valid, rejected } = validateFiles(files)
    // 单个 reject 用 toast；3+ 条合并为一条
    if (rejected.length === 1) {
      toast.error(rejected[0])
    } else if (rejected.length > 1) {
      toast.error(`${rejected.length} 个文件未能添加`, {
        description: rejected.slice(0, 3).join("\n") + (rejected.length > 3 ? `\n等共 ${rejected.length} 条` : ""),
      })
    }
    if (valid.length === 0) return
    setItems((prev) => [
      ...prev,
      ...valid.map((f) => ({ file: f, status: "pending" as const })),
    ])
  }, [validateFiles])

  // ── 移除文件 ──

  const removeItem = useCallback((index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index))
  }, [])

  // ── 拖拽事件 ──

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    if (e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files))
    }
  }, [addFiles])

  // ── 文件选择 ──

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(Array.from(e.target.files))
    }
    // 重置 input，允许重复选择同名文件
    e.target.value = ""
  }, [addFiles])

  // ── 开始上传 ──

  const handleUpload = useCallback(async () => {
    if (items.length === 0 || uploading) return

    // 创建新的 AbortController
    abortRef.current = new AbortController()

    setUploading(true)

    // 串行上传，逐个更新进度
    const updated = [...items]
    let successCount = 0
    const total = updated.length

    for (let i = 0; i < updated.length; i++) {
      // 检查是否已取消
      if (abortRef.current.signal.aborted) break

      if (updated[i].status === "done") continue

      updated[i] = { ...updated[i], status: "uploading" }
      setItems([...updated])

      try {
        const formData = new FormData()
        formData.append("files[]", updated[i].file)
        if (batchId) {
          formData.append("batch_id", batchId)
        }

        const res = await apiUpload<PaperUploadResponse>(
          "/literature/upload",
          formData
        )

        if (res.uploaded.length > 0) {
          updated[i] = {
            ...updated[i],
            status: "done",
            paperId: res.uploaded[0].id,
          }
          successCount++
        } else {
          updated[i] = { ...updated[i], status: "error", error: "服务器返回空结果" }
        }
      } catch (err) {
        // 如果是被取消的，直接退出
        if (abortRef.current?.signal.aborted) break

        updated[i] = {
          ...updated[i],
          status: "error",
          error: err instanceof Error ? err.message : "上传失败",
        }
      }
      setItems([...updated])
    }

    setUploading(false)
    abortRef.current = null

    // 完成后 Toast 汇总
    if (successCount > 0) {
      toast.success(`成功上传 ${successCount} 篇文献`)
      onUploadComplete?.()
    }
    const failCount = updated.filter((i) => i.status === "error").length
    if (failCount > 0) {
      toast.error(`${failCount} 篇上传失败`, {
        description: "请查看下方错误详情",
      })
    }
  }, [items, uploading, batchId, onUploadComplete])

  // ── 清空 ──

  const handleClear = useCallback(() => {
    if (uploading) return
    setItems([])
  }, [uploading])

  // ── 统计 ──

  const doneCount = items.filter((i) => i.status === "done").length
  const errorCount = items.filter((i) => i.status === "error").length
  const progress = items.length > 0 ? Math.round(((doneCount + errorCount) / items.length) * 100) : 0
  // 进度文案：显示当前正在上传第几个（解决进度条静止问题）
  const uploadingIndex = items.findIndex((i) => i.status === "uploading")
  const progressLabel =
    uploadingIndex >= 0
      ? `正在上传 ${uploadingIndex + 1}/${items.length}`
      : `${progress}%`

  return (
    <div className="space-y-3">
      {/* ── 拖拽区域 ── */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          "cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors",
          dragOver
            ? "border-primary bg-primary/5"
            : "border-border hover:border-muted-foreground/40 hover:bg-muted/30"
        )}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          multiple
          className="hidden"
          onChange={handleFileSelect}
        />
        <Upload className="mx-auto mb-2 h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          拖拽 PDF 文件到此处，或点击选择文件
        </p>
        <p className="mt-1 text-xs text-muted-foreground/60">
          仅支持 PDF，单文件 ≤ {MAX_SIZE_MB}MB，最多 {MAX_FILES} 个
        </p>
      </div>

      {/* ── 批次选择 ── */}
      {batches && batches.length > 0 && (
        <div className="flex items-center gap-2">
          <label className="text-sm text-muted-foreground shrink-0">上传到批次：</label>
          <select
            value={batchId}
            onChange={(e) => setBatchId(e.target.value)}
            className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring"
          >
            <option value="">（无批次）</option>
            {batches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} ({b.paper_count})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* ── 文件列表 ── */}
      {items.length > 0 && (
        <div className="space-y-2">
          {/* 头部统计 */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {items.length} 个文件
              {uploading && ` · ${progressLabel}`}
              {!uploading && doneCount > 0 && ` · 成功 ${doneCount}`}
              {!uploading && errorCount > 0 && ` · 失败 ${errorCount}`}
            </span>
            <div className="flex items-center gap-2">
              {!uploading && items.length > 0 && (
                <button
                  onClick={handleClear}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  清空
                </button>
              )}
            </div>
          </div>

          {/* 进度条 */}
          {uploading && (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}

          {/* 文件条目 */}
          <div className="max-h-48 space-y-1 overflow-y-auto">
            {items.map((item, idx) => (
              <div
                key={idx}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm",
                  item.status === "error" && "bg-destructive/10",
                  item.status === "done" && "bg-primary/5"
                )}
              >
                {/* 状态图标 */}
                {item.status === "pending" && (
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                )}
                {item.status === "uploading" && (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
                )}
                {item.status === "done" && (
                  <Check className="h-4 w-4 shrink-0 text-green-600 dark:text-green-400" />
                )}
                {item.status === "error" && (
                  <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />
                )}

                {/* 文件名 */}
                <span className="flex-1 truncate">{item.file.name}</span>

                {/* 大小 */}
                <span className="shrink-0 text-xs text-muted-foreground">
                  {(item.file.size / 1024 / 1024).toFixed(1)} MB
                </span>

                {/* 错误信息 */}
                {item.status === "error" && (
                  <span className="shrink-0 text-xs text-destructive" title={item.error}>
                    {item.error}
                  </span>
                )}

                {/* 移除按钮 */}
                {!uploading && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      removeItem(idx)
                    }}
                    className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* 上传按钮 */}
          {!uploading && items.some((i) => i.status === "pending") && (
            <button
              onClick={handleUpload}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <Upload className="h-4 w-4" />
              上传 {items.filter((i) => i.status === "pending").length} 个文件
            </button>
          )}
        </div>
      )}
    </div>
  )
}
