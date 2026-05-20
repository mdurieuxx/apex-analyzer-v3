import React, { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Star } from 'lucide-react'
import clsx from 'clsx'
import type { LiveState } from '../hooks/useWebSocket'
import { RatingBadge, ReserveQualityInline } from '../components/RatingBadge'
import { CategoryFilter } from '../components/CategoryFilter'
import { NoEventGate } from '../components/NoEventGate'
import { HistoricalStandings } from '../components/HistoricalStandings'
import { useFavorites } from '../hooks/useFavorites'
import { useCategoryColors } from '../hooks/useCategoryColors'
import { useEventView } from '../hooks/useEventView'
import type { Driver } from '../types'
import { onTrackCls, parseOnTrack } from '../utils/onTrack'
import { parseMs, estimateAvgPitS, parseGapSec, fmtGapSec } from '../utils/lapTime'

interface Props { live: LiveState }

function LapCell({ value, cls }: { value: string; cls?: string }) {
  const color =
    cls === 'best' || cls === 'sb' || cls === 'tb'
      ? 'text-purple-400 font-semibold'
      : cls === 'pb' || cls === 'improved' || cls === 'ti'
      ? 'text-green-400'
      : 'text-gray-300'
  return <td className={clsx('px-2 py-1.5 font-mono text-xs text-right', color)}>{value || '-'}</td>
}

function PosCell({ pos, pits, catStyle }: { pos: number; pits: number; catStyle?: { cls: string; inlineColor?: string } }) {
  let style: React.CSSProperties | undefined
  let cls = 'bg-gray-700'

  if (pits > 0) {
    cls = 'bg-orange-600 text-white'
  } else if (catStyle?.inlineColor) {
    const c = catStyle.inlineColor
    style = { backgroundColor: c, color: '#fff' }
    cls = ''
  } else if (catStyle?.cls) {
    cls = catStyle.cls
  } else if (pos === 1) {
    cls = 'bg-yellow-500 text-black'
  }

  return (
    <td className="px-2 py-1.5 text-center">
      <span className={clsx('inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center', cls)}
        style={style}>
        {pos}
      </span>
    </td>
  )
}

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

export function LiveTiming({ live }: Props) {
  const { drivers } = live
  const { favorites, toggle } = useFavorites()
  const navigate = useNavigate()
  const { viewedEventId } = useEventView()
  const isHistorical = viewedEventId !== null && viewedEventId !== live.activeEventId
  const catColors = useCategoryColors(drivers)
  const hasCategories = Object.keys(catColors).length > 0
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'live' | 'virtual'>('live')
  const hasSectors = drivers.some(d => d.s1 || d.s2 || d.s3)
  const hasLaps = drivers.some(d => (d.laps ?? 0) > 0)
  const isRace = live.sessionType === 'race'

  // Tick every second to refresh live pit timers
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const fmtPitTimer = (entryMs: number): string => {
    const s = Math.max(0, Math.floor((Date.now() - entryMs) / 1000))
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  }

  // Best lap across all teams (session best) — only this one gets purple
  const parseLapMs = (s: string): number => {
    const m = s.match(/^(\d+):(\d{2})[.,](\d{1,3})$/)
    if (m) return (parseInt(m[1]) * 60 + parseInt(m[2])) * 1000 + parseInt(m[3].padEnd(3, '0'))
    const m2 = s.match(/^(\d+)[.,](\d{1,3})$/)
    if (m2) return parseInt(m2[1]) * 1000 + parseInt(m2[2].padEnd(3, '0'))
    return 0
  }
  const sessionBest = drivers.reduce<string | null>((best, d) => {
    if (!d.best_lap) return best
    if (!best) return d.best_lap
    return parseLapMs(d.best_lap) < parseLapMs(best) ? d.best_lap : best
  }, null)

  // Cumulative gap: sum of intervals of all teams ahead, lap intervals replaced by that team's last_lap
  const cumulGapMap = useMemo(() => {
    const sorted = [...drivers].sort((a, b) => a.position - b.position)
    const map = new Map<string, { s: number; estimated: boolean }>()
    let cumul = 0
    let anyEst = false
    for (const d of sorted) {
      if (d.position === sorted[0].position) {
        map.set(d.driver_id, { s: 0, estimated: false })
      } else {
        const isLap = /\d+\s*(lap|tour)/i.test(d.interval ?? '')
        const intervalS = isLap
          ? parseMs(d.last_lap) / 1000
          : (() => {
              const s = (d.interval ?? '').replace(/^\+/, '').trim()
              const m = s.match(/^(\d+):(\d{2})[.,](\d{1,3})$/)
              if (m) return parseInt(m[1]) * 60 + parseInt(m[2]) + parseInt(m[3].padEnd(3, '0')) / 1000
              const m2 = s.match(/^(\d+)[.,](\d{1,3})$/)
              if (m2) return parseInt(m2[1]) + parseInt(m2[2].padEnd(3, '0')) / 1000
              return 0
            })()
        if (isLap) anyEst = true
        cumul += intervalS
        map.set(d.driver_id, { s: cumul, estimated: anyEst })
      }
    }
    return map
  }, [drivers])

  // Virtual ranking computation
  const avgPitS = useMemo(() =>
    estimateAvgPitS(live.pitHistory, drivers.map(d => d.best_lap)),
  [live.pitHistory, drivers])

  const virtualRows = useMemo(() => {
    if (!isRace) return []
    const maxPits = Math.max(...drivers.map(d => d.pits ?? 0), 0)
    const withV = drivers.map(d => {
      const gapS = parseGapSec(d.gap)
      const isLapped = gapS === null
      const pitDebt = (maxPits - (d.pits ?? 0)) * avgPitS
      return { ...d, gapS: gapS ?? 0, isLapped, virtualGapS: isLapped ? Infinity : (gapS ?? 0) + pitDebt }
    })
    const sorted = [...withV].sort((a, b) => {
      if (a.isLapped && b.isLapped) return a.position - b.position
      if (a.isLapped) return 1
      if (b.isLapped) return -1
      return a.virtualGapS - b.virtualGapS
    })
    return sorted.map((d, i) => ({ ...d, virtualPos: i + 1, positionDelta: d.position - (i + 1) }))
  }, [drivers, isRace, avgPitS])

  if (live.activeEventId === null) return <NoEventGate />

  const visibleDrivers = selectedCategory
    ? drivers.filter(d => d.category === selectedCategory)
    : drivers

  const visibleVirtual = selectedCategory
    ? virtualRows.filter(d => d.category === selectedCategory)
    : virtualRows

  if (isHistorical) return <HistoricalStandings />

  if (!drivers.length) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        {live.connected ? 'En attente des données...' : 'Non connecté à Apex Timing'}
      </div>
    )
  }

  return (
    <div className="space-y-3">
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

    {/* Tab bar — race mode only */}
    {isRace && (
      <div className="flex gap-1 border-b border-gray-800">
        <button
          onClick={() => setViewMode('live')}
          className={clsx(
            'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
            viewMode === 'live' ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'
          )}
        >
          Live
        </button>
        <button
          onClick={() => setViewMode('virtual')}
          className={clsx(
            'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
            viewMode === 'virtual' ? 'border-purple-500 text-purple-400' : 'border-transparent text-gray-500 hover:text-gray-300'
          )}
        >
          Virtuel ✦
        </button>
      </div>
    )}

    {/* Live view */}
    {viewMode === 'live' && (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
            <th className="px-2 py-2 w-8"></th>
            <th className="px-2 py-2 text-center w-10">Pos</th>
            <th className="px-2 py-2 text-center w-10">#</th>
            <th className="px-2 py-2 text-left">Équipe</th>
            <th className="px-2 py-2 text-right">Gap</th>
            <th className="px-2 py-2 text-right">Gap Σ</th>
            <th className="px-2 py-2 text-right">Int.</th>
            {hasSectors && <th className="px-2 py-2 text-right">S1</th>}
            {hasSectors && <th className="px-2 py-2 text-right">S2</th>}
            {hasSectors && <th className="px-2 py-2 text-right">S3</th>}
            <th className="px-2 py-2 text-right">Dernier</th>
            <th className="px-2 py-2 text-right">Meilleur</th>
            <th className="px-2 py-2 text-right">En piste</th>
            {hasLaps && <th className="px-2 py-2 text-center">Tours</th>}
            <th className="px-2 py-2 text-center">Stands</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {visibleDrivers.map((d, idx) => {
            const isFav = favorites.has(d.driver_id)
            const catStyle = d.category ? catColors[d.category] : undefined
            const isFlashing = live.flashingIds.has(d.driver_id)
            const ots = onTrackCls(d.on_track, d.in_pit, live.maxRelayS, isFav)
            const allPilots = live.pilotsByTeam.get(d.driver_id) ?? (d.driver_name ? [d.driver_name] : [])
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
              <PosCell pos={d.position} pits={d.in_pit ? 1 : 0} catStyle={catStyle} />
              <td className="px-2 py-1.5 text-center">
                <KartBib kart={d.kart} catStyle={catStyle} />
              </td>
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    onClick={() => navigate(`/performance?team=${encodeURIComponent(d.team || '')}`)}
                    className="font-medium text-white hover:text-blue-300 transition-colors text-left"
                  >{d.team || '-'}</button>
                  {d.kart_rating && <RatingBadge rating={d.kart_rating} showDelta />}
                </div>
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  {allPilots.map((name, i) => (
                    <button key={name} onClick={() => navigate(`/performance?pilot=${encodeURIComponent(name)}`)}
                      className={clsx('text-xs transition-colors hover:text-blue-300', name === d.driver_name ? 'text-blue-400 font-semibold' : 'text-gray-500')}>
                      {i === 0 ? '🪖' : '·'} {name}
                    </button>
                  ))}
                  {d.kart_rating?.team_level && d.kart_rating.team_level !== 'UNKNOWN' && (
                    <span className="text-xs text-purple-400 font-semibold">{d.kart_rating.team_level}</span>
                  )}
                </div>
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-300">{d.gap || '-'}</td>
              <td className="px-2 py-1.5 text-right font-mono text-xs">
                {(() => {
                  const cg = cumulGapMap.get(d.driver_id)
                  if (!cg || cg.s === 0) return <span className="text-gray-600">—</span>
                  const m = Math.floor(cg.s / 60)
                  const sec = cg.estimated ? Math.round(cg.s % 60) : (cg.s % 60)
                  const secStr = cg.estimated
                    ? String(sec).padStart(2, '0')
                    : (sec as number).toFixed(1).padStart(4, '0')
                  return cg.estimated
                    ? <span className="text-gray-500">~{m}:{secStr}</span>
                    : <span className="text-gray-200">+{m}:{secStr}</span>
                })()}
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-400">{d.interval || '-'}</td>
              {hasSectors && <LapCell value={d.s1} />}
              {hasSectors && <LapCell value={d.s2} />}
              {hasSectors && <LapCell value={d.s3} />}
              <LapCell value={d.last_lap} cls={d.last_lap_class} />
              <LapCell value={d.best_lap} cls={d.best_lap && d.best_lap === sessionBest ? 'best' : undefined} />
              <td className={clsx('px-2 py-1.5 text-right font-mono text-xs', ots.cell, ots.pulse && 'animate-pulse')}>
                {d.in_pit && live.pitEntryTimes[d.driver_id]
                  ? fmtPitTimer(live.pitEntryTimes[d.driver_id])
                  : parseOnTrack(d.on_track) !== null ? d.on_track : '-'}
              </td>
              {hasLaps && <td className="px-2 py-1.5 text-center text-gray-300">{d.laps || 0}</td>}
              <td className="px-2 py-1.5 text-center font-mono text-xs text-gray-300">
                {d.pits ?? 0}
              </td>
            </tr>
            )
          })}
        </tbody>
      </table>
    </div>
    )}

    {/* Virtual ranking view */}
    {viewMode === 'virtual' && isRace && (
    <div className="space-y-2">
      <div className="text-xs text-gray-500 flex items-center gap-2">
        <span>Stand moyen appris : <span className="text-gray-300 font-mono">
          {Math.floor(avgPitS / 60)}:{String(Math.round(avgPitS % 60)).padStart(2, '0')}
        </span></span>
        <span className="text-gray-700">·</span>
        <span>Stands max : <span className="text-gray-300">{Math.max(...drivers.map(d => d.pits ?? 0), 0)}</span></span>
        <span className="text-gray-700">·</span>
        <span className="text-gray-600 italic">Stands manquants × durée stand ajoutés à l'écart virtuel.</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
              <th className="px-2 py-2 text-center w-12">Δ pos</th>
              <th className="px-2 py-2 w-8"></th>
              <th className="px-2 py-2 text-center w-10">Virt.</th>
              <th className="px-2 py-2 text-center w-8">Réel</th>
              <th className="px-2 py-2 text-center w-10">#</th>
              <th className="px-2 py-2 text-left">Équipe</th>
              <th className="px-2 py-2 text-right">Gap virtuel</th>
              <th className="px-2 py-2 text-right">Dernier</th>
              <th className="px-2 py-2 text-right">Meilleur</th>
              <th className="px-2 py-2 text-right">En piste</th>
              <th className="px-2 py-2 text-center">Tours</th>
              <th className="px-2 py-2 text-center">Stands</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {visibleVirtual.map((d, idx) => {
              const isFav = favorites.has(d.driver_id)
              const catStyle = d.category ? catColors[d.category] : undefined
              const isFlashing = live.flashingIds.has(d.driver_id)
              const ots = onTrackCls(d.on_track, d.in_pit, live.maxRelayS, isFav)
              const allPilots = live.pilotsByTeam.get(d.driver_id) ?? (d.driver_name ? [d.driver_name] : [])
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
                <td className="px-2 py-1.5 text-center">
                  <PosDelta delta={d.positionDelta ?? 0} />
                </td>
                <td className={clsx('px-2 py-1.5 text-center', qualityBorderCls(d))}>
                  <button
                    onClick={() => toggle(d.driver_id)}
                    className={clsx('transition-colors', isFav ? 'text-yellow-400' : 'text-gray-600 hover:text-yellow-500')}
                  >
                    <Star size={13} fill={isFav ? 'currentColor' : 'none'} />
                  </button>
                </td>
                <PosCell pos={d.virtualPos ?? d.position} pits={d.in_pit ? 1 : 0} catStyle={catStyle} />
                <td className="px-2 py-1.5 text-center text-gray-500 text-xs font-mono">{d.position}</td>
                <td className="px-2 py-1.5 text-center">
                  <KartBib kart={d.kart} catStyle={catStyle} />
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-white">{d.team || '-'}</span>
                    {d.kart_rating && <RatingBadge rating={d.kart_rating} showDelta />}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                    {allPilots.map((name, i) => (
                      <span key={name} className={clsx('text-xs', name === d.driver_name ? 'text-blue-400 font-semibold' : 'text-gray-500')}>
                        {i === 0 ? '🪖' : '·'} {name}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-400">
                  {d.isLapped ? <span className="text-gray-600">+1 tour</span> : fmtGapSec(d.virtualGapS ?? 0)}
                </td>
                <LapCell value={d.last_lap} cls={d.last_lap_class} />
                <LapCell value={d.best_lap} cls={d.best_lap && d.best_lap === sessionBest ? 'best' : undefined} />
                <td className={clsx('px-2 py-1.5 text-right font-mono text-xs', ots.cell, ots.pulse && 'animate-pulse')}>
                  {d.in_pit && live.pitEntryTimes[d.driver_id]
                    ? fmtPitTimer(live.pitEntryTimes[d.driver_id])
                    : parseOnTrack(d.on_track) !== null ? d.on_track : '-'}
                </td>
                <td className="px-2 py-1.5 text-center text-gray-300">{d.laps || 0}</td>
                <td className="px-2 py-1.5 text-center font-mono text-xs text-gray-300">{d.pits ?? 0}</td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
    )}
    </div>
  )
}
