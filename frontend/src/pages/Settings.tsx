import { useState, useEffect, useCallback, useRef } from "react"
import {
  Eye,
  EyeOff,
  Zap,
  Wifi,
  WifiOff,
  Download,
  Trash2,
  Database,
  Loader2,
  Sun,
  Moon,
  CheckCircle2,
  RefreshCw,
  AlertCircle,
  ArrowRight,
} from "lucide-react"
import { toast } from "sonner"
import { apiGet, apiPut, apiPost } from "../api/client"
import { useDarkMode } from "../hooks/useDarkMode"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Card, CardHeader, CardTitle, CardContent } from "../components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../components/ui/dialog"
import type {
  ApiKeyTestResponse,
  ApiProvider,
  Settings,
  SettingsUpdateRequest,
} from "../types"
import type { UpdateStatus } from "../types/electron"

const MOONSHOT_BASE_URL = "https://api.moonshot.cn/v1"
const KIMI_CODING_BASE_URL = "https://api.kimi.com/coding/v1"
const DEEPSEEK_BASE_URL = "https://api.deepseek.com"

function inferProviderFromKey(key: string): {
  provider: ApiProvider
  baseUrl: string
} {
  const k = key.trim()
  if (k.startsWith("sk-kimi-")) {
    return { provider: "kimi-coding", baseUrl: KIMI_CODING_BASE_URL }
  }
  if (k.startsWith("sk-")) {
    return { provider: "moonshot", baseUrl: MOONSHOT_BASE_URL }
  }
  return { provider: "custom", baseUrl: MOONSHOT_BASE_URL }
}

function defaultBaseUrlForProvider(provider: ApiProvider): string {
  if (provider === "kimi-coding") return KIMI_CODING_BASE_URL
  if (provider === "deepseek") return DEEPSEEK_BASE_URL
  if (provider === "moonshot") return MOONSHOT_BASE_URL
  return MOONSHOT_BASE_URL
}

function defaultModelForProvider(provider: ApiProvider): string {
  if (provider === "deepseek") return "deepseek-v4-pro"
  if (provider === "kimi-coding") return "kimi-latest"
  return "moonshot-v1-128k"
}

// ============================================================================
// Settings 页面
// ============================================================================

export default function SettingsPage() {
  const [dark, toggleDark] = useDarkMode()

  // ── 表单状态 ──
  const [apiKey, setApiKey] = useState("")
  const [showKey, setShowKey] = useState(false)
  const [hasApiKey, setHasApiKey] = useState(false)
  const [apiKeyPreview, setApiKeyPreview] = useState("")
  const [apiProvider, setApiProvider] = useState<ApiProvider>("auto")
  const [apiBaseUrl, setApiBaseUrl] = useState(MOONSHOT_BASE_URL)
  const [testEndpoint, setTestEndpoint] = useState<string | null>(null)
  const [model, setModel] = useState("moonshot-v1-128k")
  const [availableModels, setAvailableModels] = useState<string[]>([
    "moonshot-v1-128k",
    "moonshot-v1-32k",
    "moonshot-v1-8k",
    "kimi-k2.6",
  ])
  const [temperature, setTemperature] = useState(0.3)
  const [maxTokens, setMaxTokens] = useState(8192)

  // ── 加载状态 ──
  const [settingsLoading, setSettingsLoading] = useState(true)
  const [testStatus, setTestStatus] = useState<
    null | "testing" | "connected" | "failed"
  >(null)
  const [dbStats, setDbStats] = useState<{
    db_file_size_mb: number
    tables: Record<string, number>
    pdf_count: number
    checked_at: string
  } | null>(null)

  // ── 对话框状态 ──
  const [resetDialogOpen, setResetDialogOpen] = useState(false)

  // ── 自动更新 ──
  const [appVersion, setAppVersion] = useState("")
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus>({
    state: 'idle',
    version: null,
    error: null,
  })
  const [downloadPercent, setDownloadPercent] = useState(0)
  const [checkingUpdate, setCheckingUpdate] = useState(false)

  // ── 自动保存 ──
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(null)
  const [saving, setSaving] = useState(false)
  const isMounted = useRef(true)

  // ── 加载设置 ──
  const loadSettings = useCallback(async () => {
    try {
      const data = await apiGet<Settings>("/settings/")
      if (!isMounted.current) return
      setHasApiKey(data.has_api_key)
      setApiKeyPreview(data.api_key_preview)
      if (data.api_provider) setApiProvider(data.api_provider)
      if (data.api_base_url) setApiBaseUrl(data.api_base_url)
      if (data.default_model) setModel(data.default_model)
      if (data.available_models?.length)
        setAvailableModels(data.available_models)
      if (data.temperature != null) setTemperature(data.temperature)
      if (data.max_tokens != null) setMaxTokens(data.max_tokens)
    } catch {
      toast.error("加载设置失败")
    } finally {
      if (isMounted.current) setSettingsLoading(false)
    }
  }, [])

  // ── 加载数据库统计 ──
  const loadDbStats = useCallback(async () => {
    try {
      const data = await apiGet<{
        db_file_size_mb: number
        tables: Record<string, number>
        pdf_count: number
        checked_at: string
      }>("/data/db-stats")
      if (isMounted.current) setDbStats(data)
    } catch {
      // 静默失败
    }
  }, [])

  useEffect(() => {
    isMounted.current = true
    loadSettings()
    loadDbStats()
    return () => {
      isMounted.current = false
      if (saveTimer.current) clearTimeout(saveTimer.current)
    }
  }, [loadSettings, loadDbStats])

  // ── 加载版本号 & 监听更新状态 ──
  useEffect(() => {
    const electron = window.electron
    if (!electron) {
      // 浏览器模式：无更新检测
      setAppVersion("1.0.0-dev")
      return
    }

    // 获取当前版本
    electron.getAppVersion().then((v) => {
      if (isMounted.current) setAppVersion(v)
    }).catch(() => {
      if (isMounted.current) setAppVersion("1.0.0")
    })

    // 获取初始更新状态
    electron.getUpdateStatus().then((s) => {
      if (isMounted.current) setUpdateStatus(s)
    }).catch(() => {})

    // 监听状态推送
    electron.onUpdateStatus((status: UpdateStatus) => {
      if (isMounted.current) {
        setUpdateStatus(status)
        setCheckingUpdate(false)
      }
    })

    // 监听下载进度
    electron.onUpdateDownloadProgress((progress) => {
      if (isMounted.current) {
        setDownloadPercent(progress.percent)
      }
    })

    return () => {
      electron.removeUpdateStatusListeners()
    }
  }, [])

  // ── 自动保存（debounce 3s） ──
  const debouncedSave = useCallback(
    (updates: SettingsUpdateRequest) => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(async () => {
        try {
          setSaving(true)
          await apiPut<Settings>("/settings/", updates)
          toast.success("设置已保存")
          // 更新密钥预览
          if (updates.api_key) {
            setHasApiKey(true)
          }
          await loadSettings()
        } catch {
          toast.error("保存设置失败")
        } finally {
          if (isMounted.current) setSaving(false)
        }
      }, 3000)
    },
    [loadSettings]
  )

  // ── API Key 变更 ──
  const handleApiKeyChange = useCallback(
    (value: string) => {
      setApiKey(value)
      if (apiProvider === "auto" && value.trim()) {
        const inferred = inferProviderFromKey(value)
        setApiBaseUrl(inferred.baseUrl)
      }
      if (value.trim()) {
        debouncedSave({ api_key: value })
      }
    },
    [debouncedSave, apiProvider]
  )

  const handleProviderChange = useCallback(
    (value: ApiProvider) => {
      setApiProvider(value)
      let nextUrl = apiBaseUrl
      if (value === "auto" && apiKey.trim()) {
        nextUrl = inferProviderFromKey(apiKey).baseUrl
      } else if (value !== "custom") {
        nextUrl = defaultBaseUrlForProvider(value)
      }
      const nextModel = defaultModelForProvider(value)
      setApiBaseUrl(nextUrl)
      setModel(nextModel)
      debouncedSave({
        api_provider: value,
        api_base_url: nextUrl,
        default_model: nextModel,
      })
    },
    [apiKey, apiBaseUrl, debouncedSave]
  )

  const handleBaseUrlChange = useCallback(
    (value: string) => {
      setApiBaseUrl(value)
      debouncedSave({ api_base_url: value })
    },
    [debouncedSave]
  )

  // ── 模型变更 ──
  const handleModelChange = useCallback(
    (value: string) => {
      setModel(value)
      debouncedSave({ default_model: value })
    },
    [debouncedSave]
  )

  // ── Temperature 变更 ──
  const handleTemperatureChange = useCallback(
    (value: number) => {
      setTemperature(value)
      debouncedSave({ temperature: value })
    },
    [debouncedSave]
  )

  // ── Max Tokens 变更 ──
  const handleMaxTokensChange = useCallback(
    (value: number) => {
      setMaxTokens(value)
      debouncedSave({ max_tokens: value })
    },
    [debouncedSave]
  )

  // ── 检查更新 ──
  const handleCheckUpdate = useCallback(async () => {
    const electron = window.electron
    if (!electron) {
      toast.info("更新检测仅支持桌面应用")
      return
    }
    setCheckingUpdate(true)
    try {
      const result = await electron.checkForUpdates()
      if (isMounted.current) {
        setUpdateStatus(result)
        setCheckingUpdate(false)
      }
    } catch {
      if (isMounted.current) setCheckingUpdate(false)
    }
  }, [])

  // ── 立即安装更新 ──
  const handleInstallUpdate = useCallback(() => {
    window.electron?.installUpdate()
  }, [])

  // ── 测试连接 ──
  const handleTestConnection = useCallback(async () => {
    setTestStatus("testing")
    setTestEndpoint(null)
    try {
      const res = await apiPost<ApiKeyTestResponse>("/settings/test", {
        api_key: apiKey.trim() || undefined,
        api_provider: apiProvider,
        api_base_url: apiBaseUrl,
      })
      if (res.provider && res.base_url) {
        setTestEndpoint(`${res.provider} · ${res.base_url}`)
      }
      if (res.valid) {
        if (isMounted.current) setTestStatus("connected")
        toast.success(res.message || "连接成功")
      } else {
        if (isMounted.current) setTestStatus("failed")
        toast.error(res.message || "连接失败，请检查 API Key")
      }
    } catch {
      if (isMounted.current) setTestStatus("failed")
      toast.error("连接失败，请检查 API Key")
    }
  }, [apiKey, apiProvider, apiBaseUrl])

  // ── 导出数据库 ──
  const handleExport = useCallback(async () => {
    try {
      const base = await import("../api/client").then((m) => m.resolveApiBase())
      const response = await fetch(`${base}/data/export-db`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
      if (!response.ok) {
        toast.error("导出失败")
        return
      }
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "research-assistant.db"
      a.click()
      window.URL.revokeObjectURL(url)
      toast.success("数据库导出成功")
    } catch {
      toast.error("导出失败")
    }
  }, [])

  // ── 重置数据库 ──
  const handleReset = useCallback(async () => {
    try {
      await apiPost<{ success: boolean }>("/data/reset-db", { confirm: true })
      toast.success("数据库已重置")
      setResetDialogOpen(false)
      loadDbStats()
    } catch {
      toast.error("重置数据库失败")
    }
  }, [loadDbStats])

  // ── 页面加载骨架 ──
  if (settingsLoading) {
    return (
      <div className="p-6 space-y-6 animate-pulse">
        <div className="h-6 w-24 bg-muted rounded" />
        <div className="space-y-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-40 bg-muted rounded-lg" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      {/* ── API 配置 ── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-muted-foreground" />
            API 配置
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* API Key */}
          <div className="space-y-2">
            <label className="text-sm font-medium">API Key</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(e) => handleApiKeyChange(e.target.value)}
                  placeholder={
                    hasApiKey
                      ? `已设置 · ${apiKeyPreview}`
                      : "输入 Kimi API Key · sk-..."
                  }
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showKey ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
              <Button
                onClick={handleTestConnection}
                disabled={testStatus === "testing" || !hasApiKey}
                variant="outline"
                size="sm"
                className="shrink-0"
              >
                {testStatus === "testing" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : testStatus === "connected" ? (
                  <Wifi className="h-4 w-4 text-green-500" />
                ) : testStatus === "failed" ? (
                  <WifiOff className="h-4 w-4 text-destructive" />
                ) : (
                  <Wifi className="h-4 w-4" />
                )}
                测试连接
              </Button>
            </div>
            {testStatus === "connected" && (
              <p className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                连接正常
                {testEndpoint && (
                  <span className="text-muted-foreground ml-1">
                    （{testEndpoint}）
                  </span>
                )}
              </p>
            )}
          </div>

          {/* API Provider */}
          <div className="space-y-2">
            <label className="text-sm font-medium">API Provider</label>
            <select
              value={apiProvider}
              onChange={(e) =>
                handleProviderChange(e.target.value as ApiProvider)
              }
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="auto">自动识别（推荐）</option>
              <option value="moonshot">Moonshot 通用平台</option>
              <option value="deepseek">DeepSeek</option>
              <option value="kimi-coding">Kimi For Coding</option>
              <option value="custom">自定义</option>
            </select>
          </div>

          {/* API Base URL */}
          <div className="space-y-2">
            <label className="text-sm font-medium">API Base URL</label>
            <Input
              value={apiBaseUrl}
              onChange={(e) => handleBaseUrlChange(e.target.value)}
              readOnly={apiProvider === "auto"}
              placeholder={MOONSHOT_BASE_URL}
              className={apiProvider === "auto" ? "bg-muted" : undefined}
            />
            {apiProvider === "auto" && (
              <p className="text-xs text-muted-foreground">
                根据 Key 前缀自动填充：
                sk-kimi- → Kimi Coding；sk- → Moonshot
              </p>
            )}
          </div>

          {/* 模型选择 */}
          <div className="space-y-2">
            <label className="text-sm font-medium">默认模型</label>
            <select
              value={model}
              onChange={(e) => handleModelChange(e.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {availableModels.map((m) => (
                <option key={m} value={m}>
                  {m.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      {/* ── 高级参数 ── */}
      <Card>
        <CardHeader>
          <CardTitle>高级参数</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Temperature */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium">Temperature</label>
              <span className="text-sm text-muted-foreground tabular-nums">
                {temperature.toFixed(2)}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={temperature}
              onChange={(e) =>
                handleTemperatureChange(parseFloat(e.target.value))
              }
              className="w-full h-2 bg-secondary rounded-lg appearance-none cursor-pointer accent-primary"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>精确 (0)</span>
              <span>创意 (1)</span>
            </div>
          </div>

          {/* Max Tokens */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Max Tokens</label>
            <Input
              type="number"
              min={256}
              max={32768}
              step={256}
              value={maxTokens}
              onChange={(e) =>
                handleMaxTokensChange(parseInt(e.target.value, 10) || 8192)
              }
            />
          </div>
        </CardContent>
      </Card>

      {/* ── 数据管理 ── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            数据管理
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 数据库大小 */}
          {dbStats && (
            <div className="flex items-center gap-4 text-sm">
              <span className="text-muted-foreground">数据库大小</span>
              <span className="font-mono font-medium">
                {dbStats.db_file_size_mb} MB
              </span>
              <span className="text-muted-foreground">
                {Object.values(dbStats.tables).reduce(
                  (a, b) => a + b,
                  0
                )}{" "}
                条记录
              </span>
            </div>
          )}

          <div className="flex gap-3">
            <Button
              onClick={handleExport}
              variant="outline"
              size="sm"
              className="gap-2"
            >
              <Download className="h-4 w-4" />
              导出数据库
            </Button>
            <Button
              onClick={() => setResetDialogOpen(true)}
              variant="destructive"
              size="sm"
              className="gap-2"
            >
              <Trash2 className="h-4 w-4" />
              重置数据库
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ── 主题 ── */}
      <Card>
        <CardHeader>
          <CardTitle>主题</CardTitle>
        </CardHeader>
        <CardContent>
          <button
            onClick={toggleDark}
            className="inline-flex items-center gap-3 rounded-md border border-input px-4 py-3 text-sm hover:bg-accent transition-colors"
          >
            {dark ? (
              <>
                <Moon className="h-4 w-4" />
                <span>深色模式</span>
              </>
            ) : (
              <>
                <Sun className="h-4 w-4" />
                <span>浅色模式</span>
              </>
            )}
            <span className="text-muted-foreground">
              · 点击切换
            </span>
          </button>
        </CardContent>
      </Card>

      {/* ── 关于 & 更新 ── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-muted-foreground" />
            关于 &amp; 更新
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 版本号 */}
          {appVersion && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">当前版本</span>
              <span className="font-mono font-medium">v{appVersion}</span>
            </div>
          )}

          {/* 更新状态 */}
          {updateStatus.state !== 'idle' && (
            <div className="text-sm">
              {updateStatus.state === 'checking' && (
                <p className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  正在检查更新...
                </p>
              )}
              {updateStatus.state === 'no-update' && (
                <p className="flex items-center gap-2 text-green-600 dark:text-green-400">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  已是最新版本
                </p>
              )}
              {updateStatus.state === 'downloading' && (
                <p className="flex items-center gap-2 text-blue-600 dark:text-blue-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {downloadPercent > 0
                    ? `正在下载 v${updateStatus.version} (${downloadPercent}%)`
                    : `正在下载 v${updateStatus.version}...`}
                </p>
              )}
              {updateStatus.state === 'downloaded' && (
                <div className="space-y-2">
                  <p className="flex items-center gap-2 text-green-600 dark:text-green-400">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    v{updateStatus.version} 已下载完成
                  </p>
                  <Button
                    onClick={handleInstallUpdate}
                    size="sm"
                    className="gap-2"
                  >
                    <ArrowRight className="h-4 w-4" />
                    现在重启安装
                  </Button>
                </div>
              )}
              {updateStatus.state === 'error' && (
                <p className="flex items-center gap-2 text-muted-foreground">
                  <AlertCircle className="h-3.5 w-3.5" />
                  更新检测失败
                  {updateStatus.error && (
                    <span className="text-xs">（{updateStatus.error}）</span>
                  )}
                </p>
              )}
            </div>
          )}

          {/* 手动检查按钮 */}
          <Button
            onClick={handleCheckUpdate}
            variant="outline"
            size="sm"
            disabled={checkingUpdate}
            className="gap-2"
          >
            {checkingUpdate ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            检查更新
          </Button>
        </CardContent>
      </Card>

      {/* 保存指示器 */}
      {saving && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          正在保存…
        </div>
      )}

      {/* ── 重置数据库确认对话框 ── */}
      <Dialog open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
        <DialogContent
          onClose={() => setResetDialogOpen(false)}
          className="sm:max-w-md"
        >
          <DialogHeader>
            <DialogTitle>确认重置数据库</DialogTitle>
            <DialogDescription>
              此操作将清除所有文献数据、对话历史和设置，且不可恢复。
              建议先导出数据库进行备份。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setResetDialogOpen(false)}
            >
              取消
            </Button>
            <Button variant="destructive" onClick={handleReset}>
              确认重置
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
