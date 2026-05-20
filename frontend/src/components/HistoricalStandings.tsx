import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { History, X } from 'lucide-react'
import { api } from '../api/client'
import { fmtMs } from '../utils/lapTime'
import { useEventView } from '../hooks/useEventView'
import type { EventStatsResponse } from '../types'

export function HistoricalStandings() {
  const { viewedEventId, viewedEventName, setViewed } = useEventView()
  const [data, setData] = useState<EventStatsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    if (!viewedEventId) { setData(null); return }
    setLoading(true)
    api.stats.event(viewedEventId)
      .then(r => { setData(r); setLoading(false) })
      .catch(() => setLoading(false))
  }, [viewedEventId])

  if (!viewedEventId) return null

  return (
    <div className="space-y-3">
      {/* Banner */}
      <div className="flex items-center gap-2 text-xs bg-yellow-900/20 border border-yellow-800/40 rounded px-3 py-2">
        <History size={13} className="text-yellow-400 shrink-0" />
        <span className="text-yellow-300 font-medium flex-1">Consultation : {viewedEventName}</span>
        <button
          onClick={() => navigate('/stats')}
          className="text-yellow-500 hover:text-yellow-300 transition-colors px-2 py-0.5 border border-yellow-800/40 rounded"
        >
          Voir stats
        </button>
        <button
          onClick={() => setViewed(null, '')}
          className="text-yellow-600 hover:text-yellow-300 transition-colors ml-1"
          title="Retour au direct"
        >
          <X size={13} />
        </button>
      </div>

      {loading && <div className="text-gray-500 py-8 text-center text-sm">Chargement…</div>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
                <th className="px-2 py-2 text-center w-10">Pos</th>
                <th className="px-2 py-2 text-center w-10">#</th>
                <th className="px-2 py-2 text-left">Équipe</th>
                <th className="px-2 py-2 text-center">Tours</th>
                <th className="px-2 py-2 text-right">Meilleur</th>
                <th className="px-2 py-2 text-right">Moy.</th>
                <th className="px-2 py-2 text-center">Stands</th>
                <th className="px-2 py-2 text-center">Stints</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.entries.map((e, idx) => (
                <tr key={e.id} className={idx % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'}>
                  <td className="px-2 py-1.5 text-center text-gray-500">{idx + 1}</td>
                  <td className="px-2 py-1.5 text-center text-gray-300 font-mono">{e.bib}</td>
                  <td className="px-2 py-1.5 font-medium text-white">{e.team_name}</td>
                  <td className="px-2 py-1.5 text-center text-gray-300">{e.total_laps || 0}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-green-400">{e.best_lap_ms ? fmtMs(e.best_lap_ms) : '—'}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-300">{e.avg_lap_ms ? fmtMs(e.avg_lap_ms) : '—'}</td>
                  <td className="px-2 py-1.5 text-center text-gray-300">{e.pit_count ?? 0}</td>
                  <td className="px-2 py-1.5 text-center text-gray-400">{e.stint_count ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
