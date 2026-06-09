import { useState, useEffect, useCallback, useRef } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"
import { apiGet, apiPut } from "../api/client"
import { cn } from "../lib/utils"
import type { BlockName } from "../types"

// ============================================================================
// 常量
// ============================================================================

type PaperBlock = { block_name: BlockName; content: string; updated_at: string | null }
type PaperBlocksResponse = Record<BlockName, PaperBlock | null>

const TABS: { key: BlockName; label: string }[] = [
  { key: "abstract", label: "摘要" },
  { key: "introduction", label: "引言" },
  { key: "methods", label: "方法" },
  { key: "results", label: "结果" },
  { key: "discussion", label: "讨论" },
]

const EMPTY: Record<BlockName, string> = {
  abstract: "", introduction: "", methods: "", results: "", discussion: "",
}

// ============================================================================
// 简单 Markdown → HTML（支持 H1-H3 / 粗斜体 / 列表 / 段落）
// ============================================================================

function md2html(md: string): string {
  if (!md) return ""
  let html = md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  // Headers
  html = html
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
  // Bold + italic
  html = html
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
  // Unordered lists
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>")
  html = html.replace(/(<li>.*<\/li>\s*)+/g, "<ul>$&</ul>")
  // Paragraphs (double newline)
  html = html.replace(/\n\n/g, "</p><p>")
  html = `<p>${html}</p>`
  html = html.replace(/<p>\s*<\/p>/g, "")
  return html
}

// ============================================================================
// PaperWrite 页面
// ============================================================================

export default function PaperWrite() {
  const [activeTab, setActiveTab] = useState<BlockName>("abstract")
  const [contents, setContents] = useState<Record<BlockName, string>>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<BlockName | null>(null)

  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const isMounted = useRef(true)

  // ── 加载分块 ──
  const loadBlocks = useCallback(async () => {
    try {
      const data = await apiGet<PaperBlocksResponse>("/paper/blocks")
      if (!isMounted.current) return
      const c: Record<BlockName, string> = { ...EMPTY }
      for (const t of TABS) {
        c[t.key] = data[t.key]?.content ?? ""
      }
      setContents(c)
    } catch {
      toast.error("加载论文分块失败")
    } finally {
      if (isMounted.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    isMounted.current = true
    loadBlocks()
    return () => {
      isMounted.current = false
      Object.values(saveTimers.current).forEach(clearTimeout)
    }
  }, [loadBlocks])

  // ── 保存分块 ──
  const saveBlock = useCallback(async (blockName: BlockName, content: string) => {
    try {
      setSaving(blockName)
      await apiPut(`/paper/blocks/${blockName}`, { content })
    } catch {
      toast.error("保存失败")
    } finally {
      if (isMounted.current) setSaving(null)
    }
  }, [])

  // ── 内容变更 (debounce 3s 自动保存) ──
  const handleChange = useCallback(
    (blockName: BlockName, value: string) => {
      setContents((p) => ({ ...p, [blockName]: value }))
      if (saveTimers.current[blockName]) clearTimeout(saveTimers.current[blockName])
      saveTimers.current[blockName] = setTimeout(() => {
        if (isMounted.current) saveBlock(blockName, value)
      }, 3000)
    },
    [saveBlock]
  )

  // ── 手动保存 (Ctrl+S) ──
  const handleManualSave = useCallback(() => {
    saveBlock(activeTab, contents[activeTab])
  }, [activeTab, contents, saveBlock])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        handleManualSave()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [handleManualSave])

  // ── 加载骨架 ──
  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="flex gap-2">
          {TABS.map((t) => (
            <div key={t.key} className="h-9 w-20 bg-muted rounded-md" />
          ))}
        </div>
        <div className="flex gap-4 h-[calc(100vh-220px)]">
          <div className="flex-1 bg-muted rounded-lg" />
          <div className="flex-1 bg-muted rounded-lg" />
        </div>
      </div>
    )
  }

  const currentContent = contents[activeTab]

  return (
    <div className="p-6 space-y-4 flex flex-col h-[calc(100vh-56px)]">
      {/* ── 标签页 + 保存状态 ── */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 bg-muted rounded-md p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={cn(
                "px-4 py-1.5 text-sm font-medium rounded-sm transition-colors",
                activeTab === t.key
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {saving === activeTab ? (
            <span className="flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              保存中…
            </span>
          ) : (
            <span>Ctrl+S 手动保存</span>
          )}
        </div>
      </div>

      {/* ── 编辑区 + 预览区 ── */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* 编辑区 */}
        <div className="flex-1 flex flex-col">
          <div className="text-xs text-muted-foreground mb-1 px-1">
            Markdown 编辑
          </div>
          <textarea
            value={currentContent}
            onChange={(e) => handleChange(activeTab, e.target.value)}
            placeholder={`在此撰写${TABS.find((t) => t.key === activeTab)?.label ?? ""}部分…`}
            className="flex-1 w-full resize-none rounded-md border border-input bg-background px-4 py-3 text-sm font-mono leading-relaxed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>

        {/* 预览区 */}
        <div className="flex-1 flex flex-col">
          <div className="text-xs text-muted-foreground mb-1 px-1">预览</div>
          <div className="flex-1 rounded-md border border-border bg-card p-4 overflow-y-auto">
            {currentContent ? (
              <div
                className="prose-sm prose-headings:text-foreground prose-p:text-foreground/85 prose-li:text-foreground/85 prose-strong:text-foreground prose-ul:pl-4 prose-li:my-0.5"
                dangerouslySetInnerHTML={{ __html: md2html(currentContent) }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                在左侧输入内容，在此预览
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
