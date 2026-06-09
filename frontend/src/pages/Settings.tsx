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
import type { Settings, SettingsUpdateRequest } from "../types"

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
  const [model, setModel] = useState("kimi-k2-6")
  const [availableModels, setAvailableModels] = useState<string[]>([
    "kimi-k2-5",
    "kimi-k2-6",
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
      if (value.trim()) {
        debouncedSave({ api_key: value })
      }
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

  // ── 测试连接 ──
  const handleTestConnection = useCallback(async () => {
    setTestStatus("testing")
    try {
      await apiPost<{ valid: boolean; model: string }>("/settings/test")
      if (isMounted.current) setTestStatus("connected")
      toast.success("连接成功")
    } catch {
      if (isMounted.current) setTestStatus("failed")
      toast.error("连接失败，请检查 API Key")
    }
  }, [])

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
