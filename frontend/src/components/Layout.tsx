import { useState, useEffect, useCallback } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import type { LucideIcon } from "lucide-react"
import { BookOpen, PenLine, Settings, Sun, Moon } from "lucide-react"
import { cn } from "../lib/utils"

// ============================================================================
// 暗色模式 Hook
// ============================================================================

function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState<boolean>(() => {
    const stored = localStorage.getItem("theme")
    if (stored === "dark") return true
    if (stored === "light") return false
    return window.matchMedia("(prefers-color-scheme: dark)").matches
  })

  useEffect(() => {
    const root = document.documentElement
    if (dark) {
      root.classList.add("dark")
    } else {
      root.classList.remove("dark")
    }
    localStorage.setItem("theme", dark ? "dark" : "light")
  }, [dark])

  const toggle = useCallback(() => setDark((prev) => !prev), [])

  return [dark, toggle]
}

// ============================================================================
// 导航项定义
// ============================================================================

interface NavItem {
  path: string
  label: string
  icon: LucideIcon
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "文献库", icon: BookOpen },
  { path: "/write", label: "论文撰写", icon: PenLine },
  { path: "/settings", label: "设置", icon: Settings },
]

const PAGE_TITLES: Record<string, string> = {
  "/": "文献库",
  "/write": "论文撰写",
  "/settings": "设置",
}

// ============================================================================
// Layout 组件
// ============================================================================

export default function Layout() {
  const [dark, toggleDark] = useDarkMode()
  const location = useLocation()

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* ── 侧边栏 ── */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-sidebar">
        {/* Logo / 品牌 */}
        <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-5">
          <span className="text-lg font-semibold tracking-tight text-sidebar-foreground">
            ResearchAssistant
          </span>
        </div>

        {/* 导航项 */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* 底部：暗色模式切换 */}
        <div className="border-t border-sidebar-border p-3">
          <button
            onClick={toggleDark}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            aria-label={dark ? "切换到浅色模式" : "切换到深色模式"}
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {dark ? "浅色模式" : "深色模式"}
          </button>
        </div>
      </aside>

      {/* ── 右侧主区域 ── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* 顶部栏 */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-6">
          <h2 className="text-base font-semibold text-foreground">
            {PAGE_TITLES[location.pathname] ?? "未知页面"}
          </h2>
          {/* 预留用户操作区 */}
          <div />
        </header>

        {/* 主内容区（可滚动） */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
