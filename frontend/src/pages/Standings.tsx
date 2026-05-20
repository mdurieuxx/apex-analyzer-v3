import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Star } from 'lucide-react'
import { HistoricalStandings } from '../components/HistoricalStandings'
import { useEventView } from '../hooks/useEventView'
import clsx from 'clsx'
import type { LiveState } from '../hooks/useWebSocket'
import type { Driver } from '../types'
import { RatingBadge, ReserveQualityInline } from '../components/RatingBadge'
import { CategoryFilter } from '../components/CategoryFilter'
import { NoEventGate } from '../components/NoEventGate'
import { useFavorites } from '../hooks/useFavorites'
import { useCategoryColors } from '../hooks/useCategoryColors'
import { parseMs, fmtMs, estimateAvgPitS, parseGapSec, fmtGapSec } from '../utils/lapTime'
import { onTrackCls, parseOnTrack } from '../utils/onTrack'

interface Props { live: LiveState }

// ── Shared sub-components ─────────────────────────────────────────────────────

function KartBib({ kart, catStyle }: { kart: string; catStyle?: { cls: string; inlineColor?: string } }) {
  if (!kart) return null
  const base = 'text-xs font-bold font-mono px-1.5 py-0.5 rounded'
  if (catStyle?.inlineColor) {
    return (
      <span className={`${base} text-white`} style={{ backgroundColor: catStyle.inlineColor }}>
        #{kart}
      </span>
    )
  }
  return (
    <span className={clsx(base, catStyle?.cls || 'bg-gray-700 text-gray-300')}>
      #{kart}
    </span>
  )
}

function qualityBorderCls(d: Driver): string {
  const q = d.kart_rating?.kart_quality
  if (q === 'ROCKET') return 'border-l-4 border-purple-500'
  if (q === 'FAST')   return 'border-l-4 border-green-500'
  if (q === 'BAD')    return 'border-l-4 border-red-500'
  return 'border-l-4 border-transparent'
}


function PosDelta({ delta }: { delta: number }) {
  if (delta === 0) return <span className="text-gray-600 font-mono text-xs">—</span>
  if (delta > 0) return (
    <span className="flex items-center justify-center gap-0.5 text-green-400 font-mono text-xs font-bold">
      <span>▲</span><span>{delta}</span>
    </span>
  )
  return (
    <span className="flex items-center justify-center gap-0.5 text-red-400 font-mono text-xs font-bold">
      <span>▼</span><span>{Math.abs(delta)}</span>
    </span>
  )
}

type EnrichedRow = Driver & {
  bestMs: number
  lastMs: number
  virtualPos?: number
  positionDelta?: number
  virtualGapS?: number
  isLapped?: boolean
}

// ── Live ranking tab ──────────────────────────────────────────────────────────

function LiveTab({
  rows, sessionBest, isQualifying, favorites, toggle, catColors, live,
}: {
  rows: EnrichedRow[]
  sessionBest: number
  isQualifying: boolean
  favorites: Set<string>
  toggle: (id: string) => void
  catColors: Record<string, { cls: string; inlineColor?: string }>
  live: LiveState
}) {
  const favRows = rows.filter(r => favorites.has(r.driver_id))
  const otherRows = rows.filter(r => !favorites.has(r.driver_id))
  const sorted = [...favRows, ...otherRows]
  const hasLaps = rows.some(r => (r.laps ?? 0) > 0)
  const navigate = useNavigate()

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
            <th className="px-2 py-2 w-8"></th>
            <th className="px-2 py-2 text-center w-10">{isQualifying ? '#' : 'Pos'}</th>
            <th className="px-2 py-2 text-center w-10">#</th>
            <th className="px-2 py-2 text-left">Équipe</th>
            <th className="px-2 py-2 text-right">Meilleur tour</th>
            <th className="px-2 py-2 text-right">Δ meilleur</th>
            <th className="px-2 py-2 text-right">Dernier</th>
            {!isQualifying && <th className="px-2 py-2 text-right">En piste</th>}
            {hasLaps && <th className="px-2 py-2 text-center">Tours</th>}
            {!isQualifying && <th className="px-2 py-2 text-center">Stands</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {sorted.map((d, idx) => {
            const isFav = favorites.has(d.driver_id)
            const deltaMs = sessionBest && d.bestMs ? d.bestMs - sessionBest : null
            const isSessionBest = d.bestMs > 0 && d.bestMs === sessionBest
            const catStyle = d.category ? catColors[d.category] : undefined
            const isFlashing = live.flashingIds.has(d.driver_id)
            const ots = onTrackCls(d.on_track, d.in_pit, live.maxRelayS, isFav)

            return (
              <tr
                key={d.driver_id}
                className={clsx(
                  'transition-colors',
                  isFav ? 'bg-yellow-950/20' : d.in_pit ? 'bg-orange-500/20' : idx % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50',
                  'hover:bg-gray-800/50',
                  isFlashing && 'row-flash'
                )}
              >
                <td className={clsx('px-2 py-1.5 text-center', qualityBorderCls(d))}>
                  <button
                    onClick={() => toggle(d.driver_id)}
                    className={clsx('transition-colors', isFav ? 'text-yellow-400' : 'text-gray-600 hover:text-yellow-500')}
                  >
                    <Star size={13} fill={isFav ? 'currentColor' : 'none'} />
                  </button>
                </td>
                <td className="px-2 py-1.5 text-center">
                  {(() => {
                    const pos = isQualifying ? idx + 1 : d.position
                    if (catStyle?.inlineColor) {
                      return <span className="inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center text-white"
                        style={{ backgroundColor: catStyle.inlineColor }}>{pos}</span>
                    }
                    if (catStyle?.cls) {
                      return <span className={`inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center ${catStyle.cls}`}>{pos}</span>
                    }
                    return <span className="inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center bg-gray-700 text-gray-300">{pos}</span>
                  })()}
                </td>
                <td className="px-2 py-1.5 text-center">
                  <KartBib kart={d.kart} catStyle={catStyle} />
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <button onClick={() => navigate(`/performance?team=${encodeURIComponent(d.team || '')}`)}
                      className="font-medium text-white hover:text-blue-300 transition-colors text-left">
                      {d.team || '-'}
                    </button>
                    {d.kart_rating && <RatingBadge rating={d.kart_rating} showDelta />}
                  </div>
                  {d.driver_name && (
                    <button onClick={() => navigate(`/performance?pilot=${encodeURIComponent(d.driver_name!)}`)}
                      className="text-xs text-blue-400 mt-0.5 hover:text-blue-300 transition-colors block">
                      🪖 {d.driver_name}
                    </button>
                  )}
                  {d.kart_label && d.kart_label !== '?' && !/^K\d+$/.test(d.kart_label) && (
                    <div className="text-xs text-gray-500 mt-0.5">Kart: {d.kart_label}</div>
                  )}
                </td>
                <td className={clsx(
                  'px-2 py-1.5 text-right font-mono text-xs font-semibold rounded',
                  isSessionBest ? 'text-purple-200 bg-purple-600/30' : 'text-gray-200'
                )}>
                  {fmtMs(d.bestMs)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-400">
                  {deltaMs != null && deltaMs > 0 ? `+${fmtMs(deltaMs)}` : deltaMs === 0 ? '–' : '-'}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-300">
                  {fmtMs(d.lastMs)}
                </td>
                {!isQualifying && (
                  <td className={clsx('px-2 py-1.5 text-right font-mono text-xs', ots.cell, ots.pulse && 'animate-pulse')}>
                    {parseOnTrack(d.on_track) !== null ? d.on_track : '-'}
                  </td>
                )}
                {hasLaps && <td className="px-2 py-1.5 text-center text-gray-300">{d.laps || 0}</td>}
                {!isQualifying && (
                  <td className="px-2 py-1.5 text-center font-mono text-xs text-gray-300">
                    {d.pits ?? 0}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Virtual ranking tab ───────────────────────────────────────────────────────

function VirtualTab({
  rows, sessionBest, favorites, toggle, catColors, live, avgPitS,
}: {
  rows: EnrichedRow[]
  sessionBest: number
  favorites: Set<string>
  toggle: (id: string) => void
  catColors: Record<string, { cls: string; inlineColor?: string }>
  live: LiveState
  avgPitS: number
}) {
  const virtualRows = useMemo(() => {
    const maxPits = Math.max(...rows.map(r => r.pits ?? 0), 0)
    const withV = rows.map(r => {
      const gapS = parseGapSec(r.gap)
      const isLapped = gapS === null
      const pitDebt = (maxPits - (r.pits ?? 0)) * avgPitS
      return {
        ...r,
        gapS: gapS ?? 0,
        isLapped,
        virtualGapS: isLapped ? Infinity : (gapS ?? 0) + pitDebt,
      }
    })
    const sorted = [...withV].sort((a, b) => {
      if (a.isLapped && b.isLapped) return a.position - b.position
      if (a.isLapped) return 1
      if (b.isLapped) return -1
      return a.virtualGapS - b.virtualGapS
    })
    return sorted.map((r, i) => ({
      ...r,
      virtualPos: i + 1,
      positionDelta: r.position - (i + 1),
    }))
  }, [rows, avgPitS])

  const hasLaps = rows.some(r => (r.laps ?? 0) > 0)
  const pitMin = Math.floor(avgPitS / 60)
  const pitSec = Math.round(avgPitS % 60)

  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-500 flex items-center gap-2">
        <span>
          Durée stand apprise : <span className="text-gray-300 font-mono">{pitMin}:{String(pitSec).padStart(2, '0')}</span>
        </span>
        <span className="text-gray-700">·</span>
        <span>Stands max : <span className="text-gray-300">{Math.max(...rows.map(r => r.pits ?? 0), 0)}</span></span>
        <span className="text-gray-700">·</span>
        <span className="text-gray-600 italic">Équipes avec moins de stands reculent d'autant de stands manquants × durée stand.</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
              <th className="px-2 py-2 text-center w-12">Δ pos</th>
              <th className="px-2 py-2 w-8"></th>
              <th className="px-2 py-2 text-center w-10">Virt.</th>
              <th className="px-2 py-2 text-center w-10">Réel</th>
              <th className="px-2 py-2 text-center w-10">#</th>
              <th className="px-2 py-2 text-left">Équipe</th>
              <th className="px-2 py-2 text-right">Écart virtuel</th>
              <th className="px-2 py-2 text-right">Meilleur tour</th>
              <th className="px-2 py-2 text-right">Dernier</th>
              <th className="px-2 py-2 text-right">En piste</th>
              {hasLaps && <th className="px-2 py-2 text-center">Tours</th>}
              <th className="px-2 py-2 text-center">Stands</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {virtualRows.map((d, idx) => {
              const isFav = favorites.has(d.driver_id)
              const isSessionBest = d.bestMs > 0 && d.bestMs === sessionBest
              const catStyle = d.category ? catColors[d.category] : undefined
              const isFlashing = live.flashingIds.has(d.driver_id)
              const ots = onTrackCls(d.on_track, d.in_pit, live.maxRelayS, isFav)
              const delta = d.positionDelta ?? 0

              return (
                <tr
                  key={d.driver_id}
                  className={clsx(
                    'transition-colors',
                    isFav ? 'bg-yellow-950/20' : d.in_pit ? 'bg-orange-500/20' : idx % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50',
                    'hover:bg-gray-800/50',
                    isFlashing && 'row-flash'
                  )}
                >
                  {/* Δ position */}
                  <td className="px-2 py-1.5 text-center">
                    <PosDelta delta={delta} />
                  </td>
                  {/* Favorite */}
                  <td className={clsx('px-2 py-1.5 text-center', qualityBorderCls(d))}>
                    <button
                      onClick={() => toggle(d.driver_id)}
                      className={clsx('transition-colors', isFav ? 'text-yellow-400' : 'text-gray-600 hover:text-yellow-500')}
                    >
                      <Star size={13} fill={isFav ? 'currentColor' : 'none'} />
                    </button>
                  </td>
                  {/* Virtual position */}
                  <td className="px-2 py-1.5 text-center">
                    {(() => {
                      const pos = d.virtualPos!
                      if (catStyle?.inlineColor) {
                        return <span className="inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center text-white"
                          style={{ backgroundColor: catStyle.inlineColor }}>{pos}</span>
                      }
                      if (catStyle?.cls) {
                        return <span className={`inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center ${catStyle.cls}`}>{pos}</span>
                      }
                      return <span className="inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center bg-gray-700 text-gray-300">{pos}</span>
                    })()}
                  </td>
                  {/* Real position */}
                  <td className="px-2 py-1.5 text-center text-gray-500 text-xs font-mono">{d.position}</td>
                  {/* Bib */}
                  <td className="px-2 py-1.5 text-center">
                    <KartBib kart={d.kart} catStyle={catStyle} />
                  </td>
                  {/* Team */}
                  <td className="px-2 py-1.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-white">{d.team || '-'}</span>
                      {d.kart_rating && <RatingBadge rating={d.kart_rating} showDelta />}
                    </div>
                    {d.driver_name && (
                      <div className="text-xs text-blue-400 mt-0.5">🪖 {d.driver_name}</div>
                    )}
                  </td>
                  {/* Virtual gap */}
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-400">
                    {d.isLapped ? <span className="text-gray-600">+1 tour</span> : fmtGapSec(d.virtualGapS ?? 0)}
                  </td>
                  {/* Best lap */}
                  <td className={clsx(
                    'px-2 py-1.5 text-right font-mono text-xs font-semibold rounded',
                    isSessionBest ? 'text-purple-200 bg-purple-600/30' : 'text-gray-200'
                  )}>
                    {fmtMs(d.bestMs)}
                  </td>
                  {/* Last lap */}
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-300">
                    {fmtMs(d.lastMs)}
                  </td>
                  {/* On track */}
                  <td className={clsx('px-2 py-1.5 text-right font-mono text-xs', ots.cell, ots.pulse && 'animate-pulse')}>
                    {parseOnTrack(d.on_track) !== null ? d.on_track : '-'}
                  </td>
                  {/* Laps */}
                  {hasLaps && <td className="px-2 py-1.5 text-center text-gray-300">{d.laps || 0}</td>}
                  {/* Pits */}
                  <td className="px-2 py-1.5 text-center font-mono text-xs text-gray-300">
                    {d.pits ?? 0}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Standings({ live }: Props) {
  const { favorites, toggle } = useFavorites()
  const catColors = useCategoryColors(live.drivers)
  const hasCategories = Object.keys(catColors).length > 0
  const isQualifying = live.sessionType === 'qualifying'
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'live' | 'virtual'>('live')
  const { viewedEventId } = useEventView()
  const isHistorical = viewedEventId !== null && viewedEventId !== live.activeEventId

  const avgPitS = useMemo(() =>
    estimateAvgPitS(live.pitHistory, live.drivers.map(d => d.best_lap)),
  [live.pitHistory, live.drivers])

  const rows: EnrichedRow[] = useMemo(() => {
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

  const filteredRows = selectedCategory
    ? rows.filter(r => r.category === selectedCategory)
    : rows

  if (isHistorical) return <HistoricalStandings />

  if (live.activeEventId === null) return <NoEventGate />

  if (!rows.length) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        {live.connected ? 'En attente des données...' : 'Non connecté à Apex Timing'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm font-bold uppercase text-gray-300 tracking-wide">
          Classement {isQualifying ? '— Qualifications (par meilleur temps)' : '— Course (par position)'}
        </h1>
        {favorites.size > 0 && (
          <span className="text-xs text-yellow-400">{favorites.size} favori{favorites.size > 1 ? 's' : ''}</span>
        )}
      </div>

      {(hasCategories || live.reserveSummary.unknown < 100) && (
        <div className="flex items-center gap-3 flex-wrap">
          {hasCategories && (
            <CategoryFilter
              categories={catColors}
              selected={selectedCategory}
              onChange={setSelectedCategory}
            />
          )}
          <div className="ml-auto">
            <ReserveQualityInline summary={live.reserveSummary} />
          </div>
        </div>
      )}

      {/* Tab bar — only in race mode */}
      {!isQualifying && (
        <div className="flex gap-1 border-b border-gray-800">
          <button
            onClick={() => setViewMode('live')}
            className={clsx(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              viewMode === 'live'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            )}
          >
            Classement
          </button>
          <button
            onClick={() => setViewMode('virtual')}
            className={clsx(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              viewMode === 'virtual'
                ? 'border-purple-500 text-purple-400'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            )}
          >
            Virtuel ✦
          </button>
        </div>
      )}

      {viewMode === 'live' && (
        <LiveTab
          rows={filteredRows}
          sessionBest={sessionBest}
          isQualifying={isQualifying}
          favorites={favorites}
          toggle={toggle}
          catColors={catColors}
          live={live}
        />
      )}
      {viewMode === 'virtual' && !isQualifying && (
        <VirtualTab
          rows={filteredRows}
          sessionBest={sessionBest}
          favorites={favorites}
          toggle={toggle}
          catColors={catColors}
          live={live}
          avgPitS={avgPitS}
        />
      )}
    </div>
  )
}
