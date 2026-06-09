import { useState, useEffect, useCallback } from "react"

// ============================================================================
// useDarkMode — 暗色模式 Hook（Layout + Settings 共享）
// ============================================================================

export function useDarkMode(): [boolean, () => void] {
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
