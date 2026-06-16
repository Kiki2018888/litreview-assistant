import { HashRouter, Routes, Route } from "react-router-dom"
import Layout from "./components/Layout"
import Literature from "./pages/Literature"
import Projects from "./pages/Projects"
import PaperWrite from "./pages/PaperWrite"
import Settings from "./pages/Settings"
import ChatHistory from "./pages/ChatHistory"
import Adjudication from "./pages/Adjudication"
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
          <Route path="/adjudication" element={<Adjudication />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
