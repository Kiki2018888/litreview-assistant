import { useState, useEffect, useCallback, useRef } from "react"
import {
  MessageSquare,
  BookOpen,
  Layers,
  Trash2,
  ChevronLeft,
  ChevronRight,
  MessageCircle,
  Loader2,
} from "lucide-react"
import { toast } from "sonner"
import { apiGet, apiDelete } from "../api/client"
import { Button } from "../components/ui/button"
import { Badge } from "../components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../components/ui/dialog"
import ChatPanel from "../components/ChatPanel"
import { cn } from "../lib/utils"
import type { ChatSession, SessionType, ChatSessionListResponse } from "../types"

// ============================================================================
// 类型标签映射
// ============================================================================

const TYPE_LABEL: Record<SessionType, string> = {
  literature_multi: "跨文献问答",
  literature_single: "单篇精读",
  paper_polish: "论文润色",
}

const TYPE_ICON: Record<SessionType, typeof BookOpen> = {
  literature_multi: Layers,
  literature_single: BookOpen,
  paper_polish: MessageSquare,
}

const TYPE_BADGE: Record<SessionType, "default" | "secondary" | "outline"> = {
  literature_multi: "default",
  literature_single: "secondary",
  paper_polish: "outline",
}

// ============================================================================
// ChatHistory 页面
// ============================================================================

export default function ChatHistory() {
  // ── 列表状态 ──
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10)
  const [filterType, setFilterType] = useState<SessionType | "">("")
  const [loading, setLoading] = useState(true)

  // ── 删除对话框 ──
  const [deleteTarget, setDeleteTarget] = useState<ChatSession | null>(null)
  const [deleting, setDeleting] = useState(false)

  // ── 继续对话：活动的 ChatPanel ──
  const [chatSession, setChatSession] = useState<ChatSession | null>(null)

  const isMounted = useRef(true)

  // ── 加载会话列表 ──
  const loadSessions = useCallback(async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (filterType) params.set("session_type", filterType)
      params.set("page", page.toString())
      params.set("page_size", pageSize.toString())
      const data = await apiGet<ChatSessionListResponse>(
        `/chat-sessions?${params}`
      )
      if (!isMounted.current) return
      setSessions(data.items)
      setTotal(data.total)
    } catch {
      toast.error("加载会话历史失败")
    } finally {
      if (isMounted.current) setLoading(false)
    }
  }, [page, pageSize, filterType])

  useEffect(() => {
    isMounted.current = true
    loadSessions()
    return () => {
      isMounted.current = false
    }
  }, [loadSessions])

  // ── 筛选类型变更 ──
  const handleFilterChange = useCallback((type: SessionType | "") => {
    setFilterType(type)
    setPage(1)
  }, [])

  // ── 删除会话 ──
  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return
    try {
      setDeleting(true)
      await apiDelete<{ success: boolean }>(`/chat-sessions/${deleteTarget.id}`)
      toast.success("会话已删除")
      if (chatSession?.id === deleteTarget.id) setChatSession(null)
      setDeleteTarget(null)
      loadSessions()
    } catch {
      toast.error("删除会话失败")
    } finally {
      setDeleting(false)
    }
  }, [deleteTarget, chatSession, loadSessions])

  // ── 分页 ──
  const totalPages = Math.ceil(total / pageSize)

  // ── 格式化时间 ──
  const formatTime = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleString("zh-CN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  // ── 获取会话标题 ──
  const getSessionTitle = (s: ChatSession) => {
    if (s.title) return s.title
    const firstUserMsg = s.messages?.find((m) => m.role === "user")
    if (firstUserMsg) {
      const truncated = firstUserMsg.content.slice(0, 60)
      return truncated + (firstUserMsg.content.length > 60 ? "…" : "")
    }
    return "未命名会话"
  }

  // ── 获取 ChatPanel 所需参数 ──
  const getChatPanelProps = (s: ChatSession) => {
    const isPaperPolish = s.session_type === "paper_polish"
    return {
      mode: isPaperPolish ? ("single" as const) : (
        s.session_type === "literature_single" ? ("single" as const) : ("multi" as const)
      ),
      paperId: s.primary_paper_id ?? undefined,
      paperIds: s.paper_ids ?? undefined,
      paperTitle: getSessionTitle(s),
      sessionId: s.id,
      initialMessages: s.messages?.map((m) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      })) ?? [],
    }
  }

  // ── 当 ChatPanel 打开时：全屏布局 ──
  if (chatSession) {
    return (
      <div className="flex flex-col h-[calc(100vh-56px)]">
        {/* 顶部返回栏 */}
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-muted/30 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setChatSession(null)}
            className="gap-1.5"
          >
            <ChevronLeft className="h-4 w-4" />
            返回列表
          </Button>
          <span className="text-sm font-medium truncate">
            继续对话 · {getSessionTitle(chatSession)}
          </span>
          <Badge variant={TYPE_BADGE[chatSession.session_type as SessionType] ?? "outline"}>
            {TYPE_LABEL[chatSession.session_type as SessionType] ?? chatSession.session_type}
          </Badge>
        </div>
        {/* ChatPanel 全宽 */}
        <div className="flex-1 min-h-0">
          <ChatPanel
            {...getChatPanelProps(chatSession)}
            onClose={() => setChatSession(null)}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      {/* ── 筛选栏 ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-muted-foreground mr-1">筛选：</span>
        {(["", "literature_multi", "literature_single", "paper_polish"] as const).map(
          (type) => (
            <button
              key={type}
              onClick={() => handleFilterChange(type)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                filterType === type
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              )}
            >
              {type === "" ? "全部" : TYPE_LABEL[type]}
            </button>
          )
        )}
      </div>

      {/* ── 列表 ── */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
          <MessageSquare className="h-12 w-12 mb-3 opacity-20" />
          <p className="text-sm">暂无对话历史</p>
          <p className="text-xs mt-1 opacity-50">
            开始单篇精读或跨文献问答后，会话将显示在此处
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {sessions.map((session) => {
            const Icon = TYPE_ICON[session.session_type]
            return (
              <div
                key={session.id}
                className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 hover:bg-muted/20 transition-colors"
              >
                <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">
                      {getSessionTitle(session)}
                    </span>
                    <Badge variant={TYPE_BADGE[session.session_type]}>
                      {TYPE_LABEL[session.session_type]}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 text-xs text-muted-foreground">
                    <span>创建于 {formatTime(session.created_at)}</span>
                    <span>更新于 {formatTime(session.updated_at)}</span>
                    {session.paper_ids?.length ? (
                      <span>{session.paper_ids.length} 篇文献</span>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setChatSession(session)}
                    className="gap-1.5"
                  >
                    <MessageCircle className="h-3.5 w-3.5" />
                    继续对话
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    title="删除会话"
                    onClick={() => setDeleteTarget(session)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── 分页 ── */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            <ChevronLeft className="h-4 w-4" />
            上一页
          </Button>
          <span className="text-sm text-muted-foreground px-2">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            下一页
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* ── 删除确认对话框 ── */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
      >
        <DialogContent
          onClose={() => setDeleteTarget(null)}
          className="sm:max-w-md"
        >
          <DialogHeader>
            <DialogTitle>确认删除会话</DialogTitle>
            <DialogDescription>
              删除后将不可恢复。确定要删除"
              {deleteTarget ? getSessionTitle(deleteTarget) : ""}"吗？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
