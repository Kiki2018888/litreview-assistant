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
    const p = (window as any).electron.getBackendPort().then((port: number) => {
      _cachedApiBase = `http://127.0.0.1:${port}/api/v1`
      return _cachedApiBase
    })
    _apiBasePromise = p
    return p
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

/** 失败时优先读取后端响应体的 detail 文案，解析失败回退到 `METHOD path failed: status` */
async function throwHttpError(res: Response, method: string, path: string): Promise<never> {
  const errBody = await res.json().catch(() => null)
  const detail = errBody?.detail ?? `${method} ${path} failed: ${res.status}`
  throw new Error(detail)
}

export async function apiGetText(path: string): Promise<{
  text: string
  filename: string | null
  contentType: string
}> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`)
  if (!res.ok) await throwHttpError(res, 'GET', path)
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  return {
    text: await res.text(),
    filename: match?.[1] ?? null,
    contentType: res.headers.get('Content-Type') ?? '',
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`)
  if (!res.ok) await throwHttpError(res, 'GET', path)
  return res.json()
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await throwHttpError(res, 'POST', path)
  return res.json()
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await throwHttpError(res, 'PUT', path)
  return res.json()
}

export async function apiDelete<T>(path: string): Promise<T> {
  const base = await resolveApiBase()
  const res = await fetch(`${base}${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`)
  return res.json()
}

/** Build `?a=1&b=false` from a dict; skips undefined/null/"". Booleans are kept (`false` is a real filter). */
export function buildQuery(
  params: Record<string, string | number | boolean | null | undefined>,
): string {
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    sp.set(key, String(value))
  }
  const qs = sp.toString()
  return qs ? `?${qs}` : ""
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
