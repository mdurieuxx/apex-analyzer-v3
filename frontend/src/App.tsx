import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { LiveTiming } from './pages/LiveTiming'
import { PitLane } from './pages/PitLane'
import { KartPerformancePage } from './pages/KartPerformance'
import { Settings } from './pages/Settings'
import { useWebSocket } from './hooks/useWebSocket'

export default function App() {
  const live = useWebSocket()

  return (
    <BrowserRouter>
      <Layout live={live}>
        <Routes>
          <Route path="/"            element={<LiveTiming live={live} />} />
          <Route path="/pits"        element={<PitLane live={live} />} />
          <Route path="/performance" element={<KartPerformancePage />} />
          <Route path="/settings"    element={<Settings live={live} />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
