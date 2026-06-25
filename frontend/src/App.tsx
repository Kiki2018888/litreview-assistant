/*
 * ResearchAssistant — 本地优先的 AI 科研文献分析工具
 * Copyright (C) 2026  XQ
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
import { HashRouter, Routes, Route } from "react-router-dom"
import Layout from "./components/Layout"
import Literature from "./pages/Literature"
import Projects from "./pages/Projects"
import PaperWrite from "./pages/PaperWrite"
import Settings from "./pages/Settings"
import ChatHistory from "./pages/ChatHistory"
import ComingSoon from "./components/ComingSoon"
import NotFound from "./pages/NotFound"

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Literature />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/write" element={<PaperWrite />} />
          <Route path="/history" element={<ChatHistory />} />
          {/* 信号发现模块（裁决面板）本版未发布，统一占位；后端代码与路由保留，将来换回 <Adjudication /> 即可 */}
          <Route path="/adjudication" element={<ComingSoon />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
