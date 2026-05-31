import { useState, useEffect, useMemo } from 'react'
import { CheckCircle, AlertCircle, Search } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { LiveState } from '../hooks/useWebSocket'
import type { ActivePitStop, PitHistoryEntry, PitQueueKart, ReserveSummary } from '../types'
import { RatingBadge, ReserveSummaryBar } from '../components/RatingBadge'
import { NoEventGate } from '../components/NoEventGate'

interface Props { live: LiveState & { reserveSummary?: ReserveSummary } }

function fmtDuration(s: number): string {
  const m = Math.floor(s / 60)
  const sec = String(s % 60).padStart(2, '0')
  return `${m}:${sec}`
}

function fmtLapMs(ms: number | null | undefined): string {
  if (!ms) return '-'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, '0')
  return m > 0 ? `${m}:${s}` : `${s}`
}

const QUALITY_CHIP: Record<string, string> = {
  ROCKET:  'border-purple-500/60 bg-purple-950/20',
  FAST:    'border-green-500/50  bg-green-950/15',
  MEDIUM:  'border-orange-500/50 bg-orange-950/15',
  BAD:     'border-red-500/50    bg-red-950/15',
  UNKNOWN: 'border-gray-700      bg-gray-900/50',
}

function KartChip({ kart }: { kart: PitQueueKart }) {
  const isPlaceholder = kart.is_placeholder
  const isReserved = !!kart.reserved_for_bib
  const quality = kart.rating?.kart_quality ?? 'UNKNOWN'
  const chipCls = isReserved ? 'border-blue-600/60 bg-blue-950/20' : (QUALITY_CHIP[quality] ?? QUALITY_CHIP.UNKNOWN)

  return (
    <div className={clsx(
      'flex items-center gap-2 rounded border px-2 py-1.5 text-xs transition-all',
      chipCls
    )}>
      {/* Primary label */}
      <span className="font-mono font-bold text-white text-sm min-w-[2.5rem] shrink-0">
        {isPlaceholder ? `#${kart.from_bib}` : kart.kart_label}
      </span>

      {/* Reserved-for annotation */}
      {isReserved && (
        <span className="text-blue-400 font-semibold shrink-0">→#{kart.reserved_for_bib}</span>
      )}

      {/* Deposited-by annotation (real kart from a team) */}
      {!isPlaceholder && kart.from_bib && !isReserved && (
        <span className="text-gray-500 shrink-0">↑{kart.from_bib}</span>
      )}

      <span className="ml-auto shrink-0">
        {kart.rating && kart.rating.kart_quality !== 'UNKNOWN'
          ? <RatingBadge rating={kart.rating} size="sm" />
          : <span className="text-gray-600">?</span>
        }
      </span>
    </div>
  )
}

export function PitLane({ live }: Props) {
  const [active, setActive] = useState<ActivePitStop[]>([])
  const [history, setHistory] = useState<PitHistoryEntry[]>([])
  const [minPit, setMinPit] = useState(300)
  const [filter, setFilter] = useState('')

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

  const filteredHistory = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return history
    return history.filter(p =>
      p.team.toLowerCase().includes(q) || p.bib.toLowerCase().includes(q)
    )
  }, [history, filter])

  if (live.activeEventId === null) return <NoEventGate />

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

      {/* Reserve summary */}
      {live.reserveSummary && (
        <section>
          <h2 className="text-sm font-semibold uppercase text-gray-400 mb-2 tracking-wide">
            Qualité de la réserve
          </h2>
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
            <ReserveSummaryBar summary={live.reserveSummary} />
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
                    <KartChip key={i} kart={k} />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* History */}
      <section>
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <h2 className="text-sm font-semibold uppercase text-gray-400 tracking-wide">
            Historique des stands
          </h2>
          <div className="relative flex-1 min-w-[180px] max-w-xs">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Équipe ou #..."
              className="w-full bg-gray-900 border border-gray-700 rounded-md pl-8 pr-3 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-gray-500"
            />
          </div>
          {filter && (
            <span className="text-xs text-gray-500">{filteredHistory.length} résultat{filteredHistory.length !== 1 ? 's' : ''}</span>
          )}
        </div>
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-900 text-gray-400 text-xs uppercase">
                <th className="px-3 py-2 text-left">Équipe</th>
                <th className="px-3 py-2 text-center">#</th>
                <th className="px-3 py-2 text-center">Pos.</th>
                <th className="px-3 py-2 text-center">Stand #</th>
                <th className="px-3 py-2 text-right">Durée</th>
                <th className="px-3 py-2 text-right">Tour stand</th>
                <th className="px-3 py-2 text-right">Heure</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {filteredHistory.slice(0, 50).map((p, i) => (
                <tr key={i} className="hover:bg-gray-800/50">
                  <td className="px-3 py-1.5 font-medium text-white">{p.team}</td>
                  <td className="px-3 py-1.5 text-center font-mono text-xs text-gray-300">#{p.bib}</td>
                  <td className="px-3 py-1.5 text-center text-gray-300">{p.position}</td>
                  <td className="px-3 py-1.5 text-center text-gray-300">{p.pit_number}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-xs text-gray-200">
                    {p.duration_s != null ? fmtDuration(p.duration_s) : '-'}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-xs text-orange-300">
                    {fmtLapMs(p.pit_lap_ms)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-500 text-xs">
                    {new Date(p.timestamp).toLocaleTimeString('fr-FR')}
                  </td>
                </tr>
              ))}
              {filteredHistory.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-gray-600 text-xs">
                    {filter ? 'Aucun résultat' : 'Aucun arrêt enregistré'}
                  </td>
                </tr>
              )}
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
