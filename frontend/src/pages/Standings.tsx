import { useMemo } from 'react'
import { Star } from 'lucide-react'
import clsx from 'clsx'
import type { LiveState } from '../hooks/useWebSocket'
import { RatingBadge } from '../components/RatingBadge'
import { CategoryBadge } from '../components/CategoryBadge'
import { useFavorites } from '../hooks/useFavorites'
import { useCategoryColors } from '../hooks/useCategoryColors'

interface Props { live: LiveState }

function parseMs(formatted: string): number {
  if (!formatted || formatted === '-') return 0
  const m1 = formatted.match(/^(\d+):(\d{2})[.,](\d{1,3})$/)
  if (m1) return (parseInt(m1[1]) * 60 + parseInt(m1[2])) * 1000 + parseInt(m1[3].padEnd(3, '0'))
  const m2 = formatted.match(/^(\d+)[.,](\d{1,3})$/)
  if (m2) return parseInt(m2[1]) * 1000 + parseInt(m2[2].padEnd(3, '0'))
  return 0
}

function fmtMs(ms: number): string {
  if (!ms) return '-'
  const total = ms / 1000
  const m = Math.floor(total / 60)
  const s = (total % 60).toFixed(3)
  return m > 0 ? `${m}:${s.padStart(6, '0')}` : s
}

export function Standings({ live }: Props) {
  const { favorites, toggle } = useFavorites()
  const catColors = useCategoryColors(live.drivers)
  const hasCategories = Object.keys(catColors).length > 0
  const isQualifying = live.sessionType === 'qualifying'

  const rows = useMemo(() => {
    return live.drivers.map(d => {
      const bestMs = parseMs(d.best_lap)
      const lastMs = parseMs(d.last_lap)
      return { ...d, bestMs, lastMs }
    }).sort((a, b) => {
      if (isQualifying) {
        if (!a.bestMs) return 1
        if (!b.bestMs) return -1
        return a.bestMs - b.bestMs
      }
      return a.position - b.position
    })
  }, [live.drivers, isQualifying])

  const sessionBest = useMemo(() => {
    const times = rows.map(r => r.bestMs).filter(Boolean)
    return times.length ? Math.min(...times) : 0
  }, [rows])

  const favRows = rows.filter(r => favorites.has(r.driver_id))
  const otherRows = rows.filter(r => !favorites.has(r.driver_id))
  const sortedRows = [...favRows, ...otherRows]

  if (!rows.length) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        {live.connected ? 'En attente des données...' : 'Non connecté à Apex Timing'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-bold uppercase text-gray-300 tracking-wide">
          Classement {isQualifying ? '— Qualifications (par meilleur temps)' : '— Course (par position)'}
        </h1>
        {favorites.size > 0 && (
          <span className="text-xs text-yellow-400">{favorites.size} favori{favorites.size > 1 ? 's' : ''}</span>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
              <th className="px-2 py-2 w-8"></th>
              <th className="px-2 py-2 text-center w-10">{isQualifying ? '#' : 'Pos'}</th>
              <th className="px-2 py-2 text-left">Équipe</th>
              <th className="px-2 py-2 text-center">Kart</th>
              <th className="px-2 py-2 text-right">Meilleur tour</th>
              <th className="px-2 py-2 text-right">Δ meilleur</th>
              <th className="px-2 py-2 text-right">Dernier</th>
              <th className="px-2 py-2 text-center">Tours</th>
              {!isQualifying && <th className="px-2 py-2 text-center">Stands</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {sortedRows.map((d, idx) => {
              const isFav = favorites.has(d.driver_id)
              const deltaMs = sessionBest && d.bestMs ? d.bestMs - sessionBest : null
              const isSessionBest = d.bestMs > 0 && d.bestMs === sessionBest

              return (
                <tr
                  key={d.driver_id}
                  className={clsx(
                    'transition-colors',
                    isFav ? 'bg-yellow-950/20' : d.pits > 0 ? 'bg-orange-950/30' : idx % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50',
                    'hover:bg-gray-800/50'
                  )}
                >
                  <td className="px-2 py-1.5 text-center">
                    <button
                      onClick={() => toggle(d.driver_id)}
                      className={clsx('transition-colors', isFav ? 'text-yellow-400' : 'text-gray-600 hover:text-yellow-500')}
                    >
                      <Star size={13} fill={isFav ? 'currentColor' : 'none'} />
                    </button>
                  </td>
                  <td className="px-2 py-1.5 text-center text-gray-300 font-mono text-xs">
                    {isQualifying ? idx + 1 : d.position}
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      {hasCategories && d.category && (
                        <CategoryBadge category={d.category} colorClass={catColors[d.category] ?? ''} />
                      )}
                      <span className="font-medium text-white">{d.team || '-'}</span>
                      {d.kart_rating && <RatingBadge rating={d.kart_rating} showDelta />}
                    </div>
                    {d.driver_name && (
                      <div className="text-xs text-blue-400 mt-0.5">🪖 {d.driver_name}</div>
                    )}
                    {d.kart_label && d.kart_label !== '?' && (
                      <div className="text-xs text-gray-500 mt-0.5">Kart: {d.kart_label}</div>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <span className="bg-gray-700 text-white text-xs font-mono px-2 py-0.5 rounded">
                      #{d.kart}
                    </span>
                  </td>
                  <td className={clsx(
                    'px-2 py-1.5 text-right font-mono text-xs font-semibold',
                    isSessionBest ? 'text-purple-400' : 'text-gray-200'
                  )}>
                    {fmtMs(d.bestMs)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-400">
                    {deltaMs != null && deltaMs > 0 ? `+${fmtMs(deltaMs)}` : deltaMs === 0 ? '–' : '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-300">
                    {fmtMs(d.lastMs)}
                  </td>
                  <td className="px-2 py-1.5 text-center text-gray-300">{d.laps || 0}</td>
                  {!isQualifying && (
                    <td className="px-2 py-1.5 text-center">
                      {d.pits > 0 ? (
                        <span className="bg-orange-600 text-white text-xs px-2 py-0.5 rounded-full font-bold">
                          {d.pits}
                        </span>
                      ) : (
                        <span className="text-gray-600">0</span>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
