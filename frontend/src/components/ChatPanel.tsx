import { useState, useCallback, useRef, useEffect } from "react"
import {
  X,
  Send,
  StopCircle,
  RefreshCw,
  BookOpen,
  Layers,
  Loader2,
  ToggleLeft,
  ToggleRight,
} from "lucide-react"
import { toast } from "sonner"
import { cn } from "../lib/utils"
import { useSSE } from "../hooks/useSSE"
import type { SSEEvent } from "../hooks/useSSE"

// ============================================================================
// 类型定义
// ============================================================================

interface Message {
  role: "user" | "assistant"
  content: string
}

interface ChatPanelProps {
  /** 聊天模式 */
  mode: "single" | "multi"
  /** 单篇模式：文献 ID */
  paperId?: string
  /** 跨文献模式：文献 ID 列表 */
  paperIds?: string[]
  /** 文献标题（用于显示） */
  paperTitle?: string
  /** 关闭面板回调 */
  onClose: () => void
}

// ============================================================================
// ChatPanel 组件
// ============================================================================

export default function ChatPanel({
  mode,
  paperId,
  paperIds,
  paperTitle,
  onClose,
}: ChatPanelProps) {
  // ── 对话状态 ──
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [sessionId, setSessionId] = useState<string | null>(null)

  // ── 单篇模式：全文开关 ──
  const [useFulltext, setUseFulltext] = useState(false)

  // ── SSE ──
  const { start, abort, isLoading: streaming } = useSSE()

  // ── 滚动容器 ref ──
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // ── 自动滚动到底部 ──
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // ── SSE 事件处理 ──
  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      switch (event.type) {
        case "chunk": {
          const content = (event.content as string) ?? ""
          setMessages((prev) => {
            const last = prev[prev.length - 1]
            // 如果最后一条是用户消息，新建 AI 消息
            if (!last || last.role === "user") {
              return [...prev, { role: "assistant", content }]
            }
            // 否则追加到当前 AI 消息
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + content },
            ]
          })
          break
        }
        case "result": {
          const sid = event.session_id as string | undefined
          if (sid) setSessionId(sid)
          break
        }
        case "error": {
          toast.error((event.message as string) ?? "AI 服务异常")
          setMessages((prev) => {
            const last = prev[prev.length - 1]
            if (last?.role === "assistant" && !last.content) {
              return prev.slice(0, -1)
            }
            return prev
          })
          break
        }
        case "done":
          // 流正常结束
          break
      }
    },
    []
  )

  // ── SSE 错误处理 ──
  const handleSSEError = useCallback((error: string) => {
    toast.error(error)
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.role === "assistant" && !last.content) {
        return prev.slice(0, -1)
      }
      return prev
    })
  }, [])

  // ── 发起提问 ──
  const handleSend = useCallback(() => {
    const question = input.trim()
    if (!question || streaming) return

    // 添加用户消息
    const userMsg: Message = { role: "user", content: question }
    setMessages((prev) => [...prev, userMsg])
    setInput("")

    // 构建请求体
    const body: Record<string, unknown> = { question }
    if (sessionId) body.session_id = sessionId

    let url: string
    if (mode === "single" && paperId) {
      url = `/literature/${paperId}/chat`
      body.use_fulltext = useFulltext
    } else if (mode === "multi" && paperIds && paperIds.length > 0) {
      url = "/literature/chat"
      body.paper_ids = paperIds
    } else {
      toast.error("聊天参数不完整")
      return
    }

    start({
      url,
      method: "POST",
      body,
      onEvent: handleSSEEvent,
      onError: handleSSEError,
      onDone: () => {
        // 流结束，聚焦输入框
        inputRef.current?.focus()
      },
    })
  }, [
    input,
    streaming,
    sessionId,
    mode,
    paperId,
    paperIds,
    useFulltext,
    start,
    handleSSEEvent,
    handleSSEError,
  ])

  // ── 停止生成 ──
  const handleStop = useCallback(() => {
    abort()
    toast.info("已停止生成")
  }, [abort])

  // ── 重试最后一条消息 ──
  const handleRetry = useCallback(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user")
    if (!lastUser) return
    // 移除最后的 AI 消息
    setMessages((prev) => {
      const idx = prev.findLastIndex((m) => m.role === "assistant")
      if (idx >= 0) return prev.slice(0, idx)
      return prev
    })
    // 重新发送
    const body: Record<string, unknown> = { question: lastUser.content }
    if (sessionId) body.session_id = sessionId

    let url: string
    if (mode === "single" && paperId) {
      url = `/literature/${paperId}/chat`
      body.use_fulltext = useFulltext
    } else if (mode === "multi" && paperIds && paperIds.length > 0) {
      url = "/literature/chat"
      body.paper_ids = paperIds
    } else {
      return
    }

    start({
      url,
      method: "POST",
      body,
      onEvent: handleSSEEvent,
      onError: handleSSEError,
      onDone: () => inputRef.current?.focus(),
    })
  }, [messages, sessionId, mode, paperId, paperIds, useFulltext, start, handleSSEEvent, handleSSEError])

  // ── 键盘事件 ──
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  // ── 渲染消息 ──
  const renderMessage = (msg: Message, idx: number) => {
    const isUser = msg.role === "user"
    const isLastAI =
      !isUser &&
      idx === messages.length - 1 &&
      streaming

    return (
      <div
        key={idx}
        className={cn("flex", isUser ? "justify-end" : "justify-start")}
      >
        <div
          className={cn(
            "max-w-[85%] rounded-lg px-4 py-2.5 text-sm leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-foreground"
          )}
        >
          <div className="whitespace-pre-wrap break-words">
            {msg.content || (
              isLastAI && (
                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  AI 正在思考…
                </span>
              )
            )}
          </div>
          {/* 打字光标 */}
          {isLastAI && msg.content && (
            <span className="inline-block w-0.5 h-4 bg-foreground/60 ml-0.5 align-middle animate-pulse" />
          )}
        </div>
      </div>
    )
  }

  // ── 面板标题 ──
  const headerTitle =
    mode === "single"
      ? `精读：${paperTitle?.slice(0, 40) ?? paperId ?? "文献"}`
      : `跨文献问答 · ${paperIds?.length ?? 0} 篇`

  return (
    <div className="flex flex-col h-full bg-background">
      {/* ── 顶部标题栏 ── */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5 shrink-0 bg-muted/30">
        <div className="flex items-center gap-2 min-w-0">
          {mode === "single" ? (
            <BookOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <Layers className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <h3
            className="text-sm font-semibold truncate"
            title={headerTitle}
          >
            {headerTitle}
          </h3>

          {/* 单篇模式：全文开关 */}
          {mode === "single" && (
            <button
              onClick={() => setUseFulltext((v) => !v)}
              className={cn(
                "ml-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs transition-colors",
                useFulltext
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
              title={useFulltext ? "使用全文模式" : "使用摘要模式"}
            >
              {useFulltext ? (
                <ToggleRight className="h-3.5 w-3.5" />
              ) : (
                <ToggleLeft className="h-3.5 w-3.5" />
              )}
              <span className="hidden sm:inline">全文</span>
            </button>
          )}
        </div>

        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* ── 消息列表 ── */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3"
      >
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <BookOpen className="h-12 w-12 mb-3 opacity-20" />
            <p className="text-sm">
              {mode === "single"
                ? "向 AI 提问，精读这篇文献"
                : "向 AI 提问，基于多篇文献综述回答"}
            </p>
            <p className="text-xs mt-1 opacity-50">
              支持追问和深入讨论
            </p>
          </div>
        )}
        {messages.map(renderMessage)}
        {/* 底部留白，确保最后一条消息不被输入框遮挡 */}
        <div className="h-2" />
      </div>

      {/* ── 底部输入区 ── */}
      <div className="border-t border-border px-4 py-3 shrink-0 bg-muted/20">
        <div className="flex items-end gap-2">
          {/* 输入框 */}
          <div className="flex-1 relative">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                streaming ? "AI 正在回复…" : "输入问题，按 Enter 发送…"
              }
              disabled={streaming}
              className="w-full rounded-md border border-input bg-background px-3 py-2 pr-10 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring disabled:opacity-50"
            />
            {/* 重试按钮（最后一条是 AI 空消息时显示） */}
            {!streaming &&
              messages.length > 0 &&
              messages[messages.length - 1]?.role === "user" && (
                <button
                  onClick={handleRetry}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground transition-colors"
                  title="重试"
                >
                  <RefreshCw className="h-4 w-4" />
                </button>
              )}
          </div>

          {/* 发送/停止按钮 */}
          {streaming ? (
            <button
              onClick={handleStop}
              className="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors shrink-0"
            >
              <StopCircle className="h-4 w-4" />
              <span className="hidden sm:inline">停止</span>
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40 shrink-0"
            >
              <Send className="h-4 w-4" />
              <span className="hidden sm:inline">发送</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
