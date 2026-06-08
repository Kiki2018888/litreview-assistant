import { HashRouter, Routes, Route } from "react-router-dom"
import Layout from "./components/Layout"
import Literature from "./pages/Literature"
import PaperWrite from "./pages/PaperWrite"
import Settings from "./pages/Settings"
import NotFound from "./pages/NotFound"

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Literature />} />
          <Route path="/write" element={<PaperWrite />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
