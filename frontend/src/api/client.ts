// ============================================================================
// 动态 API Base URL
// - 浏览器开发模式：走 Vite 代理 → /api/v1
// - Electron 模式：通过 IPC 获取实际端口（8000-8010 fallback）
// ============================================================================

let _cachedApiBase: string | null = null
let _apiBasePromise: Promise<string> | null = null

export async function resolveApiBase(): Promise<string> {
  if (_cachedApiBase) return _cachedApiBase
  if (_apiBasePromise) return _apiBasePromise

  if (typeof window !== 'undefined' && (window as any).electron?.getBackendPort) {
    _apiBasePromise = (window as any).electron.getBackendPort().then((port: number) => {
      _cachedApiBase = `http://127.0.0.1:${port}/api/v1`
      return _cachedApiBase
    })
    return _apiBasePromise
  }

  _cachedApiBase = '/api/v1'
  return _cachedApiBase
}

/** 供 SSE 等需要同步获取 base URL 的场景（仅浏览器 dev 模式有效） */
export function getApiBaseSync(): string {
  return _cachedApiBase ?? '/api/v1'
}

// ============================================================================
// HTTP 方法
// ============================================================================

export async function apiGet<T>(path: string): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json()
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`)
  return res.json()
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`PUT ${path} failed: ${res.status}`)
  return res.json()
}

export async function apiDelete<T>(path: string): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`)
  return res.json()
}

/** 文件上传（multipart/form-data），不做 JSON 编码 */
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    const detail = errBody?.detail ?? `Upload failed: ${res.status}`
    throw new Error(detail)
  }
  return res.json()
}
