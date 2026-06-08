import { useCallback, useRef, useState } from "react"
import { resolveApiBase } from "../api/client"

// ============================================================================
// 类型定义
// ============================================================================

export interface SSEEvent {
  type: string
  [key: string]: unknown
}

export interface UseSSEOptions {
  /** API 路径（不含 base，如 "/literature/xxx/chat"） */
  url: string
  /** HTTP 方法，默认 POST */
  method?: "GET" | "POST"
  /** POST 请求体 */
  body?: Record<string, unknown>
  /** SSE 事件回调 */
  onEvent: (event: SSEEvent) => void
  /** 错误回调（连接失败、HTTP 错误等） */
  onError?: (error: string) => void
  /** 流结束回调 */
  onDone?: () => void
  /** 最大重试次数，默认 3。设为 0 禁用重连。 */
  maxRetries?: number
  /** 是否禁用自动重连（聊天流等不应重复提交同一问题的场景） */
  disableRetry?: boolean
}

// ============================================================================
// useSSE Hook
// ============================================================================

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null)
  const retryCountRef = useRef(0)
  const [isLoading, setIsLoading] = useState(false)

  // ── 中止当前连接 ──
  const abort = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    retryCountRef.current = 0
    setIsLoading(false)
  }, [])

  // ── 判断是否为网络断开类错误（允许重连） ──
  const isNetworkError = (err: unknown): boolean => {
    if (!(err instanceof Error)) return false
    // TypeError：fetch 无法连接（DNS 失败、连接拒绝等）
    if (err.name === "TypeError") return true
    // Failed to fetch：浏览器/Electron 网络层错误
    if (err.message.includes("Failed to fetch")) return true
    // 其他网络层错误
    if (
      err.message.includes("NetworkError") ||
      err.message.includes("network") ||
      err.message.includes("connect")
    )
      return true
    return false
  }

  // ── 判断是否为 HTTP 错误（不重连） ──
  const isHttpError = (err: unknown): boolean => {
    if (!(err instanceof Error)) return false
    return /^HTTP \d{3}:/.test(err.message)
  }

  // ── 核心：发起 SSE 请求 ──
  const start = useCallback(
    (options: UseSSEOptions) => {
      const {
        url,
        method = "POST",
        body,
        onEvent,
        onError,
        onDone,
        maxRetries = 3,
        disableRetry = false,
      } = options

      // 禁止并发：先中止旧连接
      abortRef.current?.abort()
      abortRef.current = new AbortController()
      const signal = abortRef.current.signal
      retryCountRef.current = 0
      setIsLoading(true)

      const connect = async () => {
        try {
          const base = await resolveApiBase()
          const fetchOptions: RequestInit = {
            method,
            headers:
              method === "POST"
                ? { "Content-Type": "application/json" }
                : {},
            signal,
          }
          if (method === "POST" && body) {
            fetchOptions.body = JSON.stringify(body)
          }

          const res = await fetch(`${base}${url}`, fetchOptions)

          if (!res.ok) {
            const errText = await res.text().catch(() => "")
            throw new Error(`HTTP ${res.status}: ${errText || res.statusText}`)
          }

          // 连接成功，重置重试计数
          retryCountRef.current = 0

          const reader = res.body?.getReader()
          if (!reader) throw new Error("无法读取 SSE 流")

          const decoder = new TextDecoder()
          let buffer = ""

          while (true) {
            if (signal.aborted) break

            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })

            // SSE 事件以 \n\n 分隔
            const parts = buffer.split("\n\n")
            // 最后一段可能是不完整的事件，保留到下次
            buffer = parts.pop() ?? ""

            for (const part of parts) {
              const trimmed = part.trim()
              if (!trimmed) continue

              // 解析 data: 行
              const lines = trimmed.split("\n")
              for (const line of lines) {
                const t = line.trim()
                if (t.startsWith("data: ")) {
                  try {
                    const event: SSEEvent = JSON.parse(t.slice(6))
                    onEvent(event)

                    if (event.type === "done") {
                      retryCountRef.current = 0
                      setIsLoading(false)
                      onDone?.()
                    }
                  } catch {
                    // 忽略 JSON 解析错误
                  }
                }
              }
            }
          }

          // reader 正常结束（done=true）
          retryCountRef.current = 0
          setIsLoading(false)
        } catch (err) {
          if (signal.aborted) {
            setIsLoading(false)
            return
          }

          const msg = err instanceof Error ? err.message : "SSE 连接失败"

          // ── HTTP 错误（4xx/5xx）：不重连，直接报错 ──
          if (isHttpError(err)) {
            setIsLoading(false)
            onError?.(msg)
            return
          }

          // ── 禁用重连或不是网络错误：不重连 ──
          if (disableRetry || !isNetworkError(err)) {
            setIsLoading(false)
            onError?.(msg)
            return
          }

          // ── 网络错误：指数退避重连 ──
          if (retryCountRef.current < maxRetries) {
            retryCountRef.current += 1
            const delay = Math.pow(2, retryCountRef.current - 1) * 1000 // 1s, 2s, 4s
            console.warn(
              `[useSSE] 重连 ${retryCountRef.current}/${maxRetries}，${delay}ms 后…`
            )
            await new Promise((r) => setTimeout(r, delay))
            if (!signal.aborted) {
              connect()
              return
            }
          }

          setIsLoading(false)
          onError?.(msg)
        }
      }

      connect()
    },
    []
  )

  return { start, abort, isLoading }
}
