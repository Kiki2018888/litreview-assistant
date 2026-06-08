import Literature from './pages/Literature'
import PaperWrite from './pages/PaperWrite'
import Settings from './pages/Settings'

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b p-4">
        <h1 className="text-xl font-semibold">ResearchAssistant</h1>
      </header>
      <main className="p-4">
        <Literature />
        <PaperWrite />
        <Settings />
      </main>
    </div>
  )
}
