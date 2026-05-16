import { useState, useEffect } from 'react'
import { Clock, CheckCircle, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { LiveState } from '../hooks/useWebSocket'
import type { ActivePitStop, PitHistoryEntry, PitQueueKart } from '../types'

interface Props { live: LiveState }

function fmtDuration(s: number): string {
  const m = Math.floor(s / 60)
  const sec = String(s % 60).padStart(2, '0')
  return `${m}:${sec}`
}

function KartChip({ kart, minPit }: { kart: PitQueueKart; minPit: number }) {
  const [elapsed, setElapsed] = useState(kart.seconds_in_pit)

  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(t)
  }, [])

  const eligible = elapsed >= minPit
  const ratio = Math.min(elapsed / minPit, 1)

  return (
    <div className={clsx(
      'relative rounded-lg border p-3 text-center transition-all',
      eligible ? 'border-green-500 bg-green-950/30' : 'border-gray-700 bg-gray-900'
    )}>
      {/* Progress bar */}
      <div className="absolute bottom-0 left-0 h-1 rounded-b-lg bg-green-500/40 transition-all" style={{ width: `${ratio * 100}%` }} />

      <div className="text-lg font-bold font-mono text-white">{kart.kart_label}</div>
      <div className={clsx('text-xs mt-1 font-mono', eligible ? 'text-green-400' : 'text-orange-400')}>
        {fmtDuration(elapsed)}
      </div>
      {eligible ? (
        <CheckCircle size={14} className="mx-auto mt-1 text-green-400" />
      ) : (
        <Clock size={14} className="mx-auto mt-1 text-orange-400" />
      )}
    </div>
  )
}

export function PitLane({ live }: Props) {
  const [active, setActive] = useState<ActivePitStop[]>([])
  const [history, setHistory] = useState<PitHistoryEntry[]>([])
  const [minPit, setMinPit] = useState(300)

  useEffect(() => {
    api.pits.live().then(r => setActive(r.active)).catch(() => {})
    api.pits.history().then(r => setHistory(r.history)).catch(() => {})
    api.config.get().then(c => setMinPit(c.min_pit_duration_s)).catch(() => {})
    const t = setInterval(() => {
      api.pits.live().then(r => setActive(r.active)).catch(() => {})
    }, 5000)
    return () => clearInterval(t)
  }, [])

  // Sync history from live state
  useEffect(() => {
    if (live.pitHistory.length) setHistory(live.pitHistory)
  }, [live.pitHistory])

  return (
    <div className="space-y-6">
      {/* Active pits */}
      {active.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold uppercase text-orange-400 mb-3 tracking-wide">
            Actuellement aux stands
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {active.map(ps => (
              <ActivePitCard key={ps.driver_id} ps={ps} minPit={minPit} />
            ))}
          </div>
        </section>
      )}

      {/* Lanes */}
      <section>
        <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3 tracking-wide">
          Files de réserve
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {live.lanes.map(lane => (
            <div key={lane.lane} className="bg-gray-900 rounded-lg border border-gray-800 p-3">
              <h3 className="text-xs font-bold text-gray-400 uppercase mb-3">File {lane.lane}</h3>
              <div className="space-y-2">
                {lane.karts.length === 0 ? (
                  <div className="text-center text-gray-600 text-xs py-4">Vide</div>
                ) : (
                  lane.karts.map((k, i) => (
                    <KartChip key={i} kart={k} minPit={minPit} />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* History */}
      <section>
        <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3 tracking-wide">
          Historique des stands
        </h2>
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-900 text-gray-400 text-xs uppercase">
                <th className="px-3 py-2 text-left">Équipe</th>
                <th className="px-3 py-2 text-center">Bib</th>
                <th className="px-3 py-2 text-center">Kart entrant</th>
                <th className="px-3 py-2 text-center">Kart sortant</th>
                <th className="px-3 py-2 text-center">Pos.</th>
                <th className="px-3 py-2 text-center">Stand #</th>
                <th className="px-3 py-2 text-right">Durée</th>
                <th className="px-3 py-2 text-right">Heure</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {history.slice(0, 50).map((p, i) => (
                <tr key={i} className="hover:bg-gray-800/50">
                  <td className="px-3 py-1.5 font-medium">{p.team}</td>
                  <td className="px-3 py-1.5 text-center font-mono text-xs">#{p.bib}</td>
                  <td className="px-3 py-1.5 text-center font-mono text-xs text-orange-400">{p.kart_in || '-'}</td>
                  <td className="px-3 py-1.5 text-center font-mono text-xs text-green-400">{p.kart_out || '?'}</td>
                  <td className="px-3 py-1.5 text-center">{p.position}</td>
                  <td className="px-3 py-1.5 text-center">{p.pit_number}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-xs">
                    {p.duration_s != null ? fmtDuration(p.duration_s) : '-'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-400 text-xs">
                    {new Date(p.timestamp).toLocaleTimeString('fr-FR')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function ActivePitCard({ ps, minPit }: { ps: ActivePitStop; minPit: number }) {
  const [elapsed, setElapsed] = useState(ps.seconds_in_pit)
  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const eligible = elapsed >= minPit
  return (
    <div className={clsx(
      'rounded-lg border p-4',
      eligible ? 'border-green-500 bg-green-950/20' : 'border-orange-500 bg-orange-950/20'
    )}>
      <div className="flex justify-between items-start">
        <div>
          <div className="font-bold text-white">{ps.team}</div>
          <div className="text-xs text-gray-400">#{ps.bib} · Stand #{ps.pit_number}</div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-mono font-bold text-white">{fmtDuration(elapsed)}</div>
          {eligible
            ? <div className="text-xs text-green-400 flex items-center gap-1 justify-end"><CheckCircle size={12} /> Prêt</div>
            : <div className="text-xs text-orange-400 flex items-center gap-1 justify-end"><AlertCircle size={12} /> Attente min</div>
          }
        </div>
      </div>
      {ps.kart_label && ps.kart_label !== '?' && (
        <div className="mt-2 text-xs text-gray-500">Kart: <span className="text-orange-300 font-mono">{ps.kart_label}</span></div>
      )}
      <div className="mt-2 text-xs text-gray-500">Position au moment du stand: <span className="text-white">P{ps.position}</span></div>
    </div>
  )
}
