import { useCallback, useRef } from 'react'

export interface SSEEvent {
  type: string
  [key: string]: unknown
}

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null)

  const connect = useCallback(
    (url: string, onEvent: (event: SSEEvent) => void, onDone?: () => void) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      fetch(`/api/v1${url}`, { signal: controller.signal })
        .then(async (response) => {
          const reader = response.body?.getReader()
          if (!reader) return
          const decoder = new TextDecoder()
          let buffer = ''
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const event = JSON.parse(line.slice(6))
                  onEvent(event)
                  if (event.type === 'done') onDone?.()
                } catch { /* ignore parse errors */ }
              }
            }
          }
        })
        .catch(() => { /* ignore abort errors */ })

      return () => controller.abort()
    },
    []
  )

  return { connect, abort: () => abortRef.current?.abort() }
}
