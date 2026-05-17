import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { LiveTiming } from './pages/LiveTiming'
import { Standings } from './pages/Standings'
import { PitLane } from './pages/PitLane'
import { KartPerformancePage } from './pages/KartPerformance'
import { Settings } from './pages/Settings'
import { Circuits } from './pages/Circuits'
import { Events } from './pages/Events'
import { useWebSocket } from './hooks/useWebSocket'

export default function App() {
  const live = useWebSocket()

  return (
    <BrowserRouter>
      <Layout live={live}>
        <Routes>
          <Route path="/"            element={<LiveTiming live={live} />} />
          <Route path="/standings"   element={<Standings live={live} />} />
          <Route path="/pits"        element={<PitLane live={live} />} />
          <Route path="/performance" element={<KartPerformancePage />} />
          <Route path="/circuits"    element={<Circuits />} />
          <Route path="/events"      element={<Events />} />
          <Route path="/settings"    element={<Settings live={live} />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
