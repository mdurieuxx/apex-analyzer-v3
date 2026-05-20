import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useEventView } from '../hooks/useEventView'
import { Search, ChevronDown, ChevronRight, Users, Flag, Trophy, Clock, X } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import { fmtMs } from '../utils/lapTime'
import { median, speedStars, consistencyStars, globalScore, RatingCell, fmtCV } from '../utils/statsHelpers'
import type {
  KartingEvent, Circuit, EntryDetail, StintStat,
  PilotStat, EventStatsResponse, SearchResult,
} from '../types'

// ── helpers ────────────────────────────────────────────────────────────────

function fmtDur(ms: number | null) {
  if (!ms || ms <= 0) return '-'
  const s = Math.round(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function fmtTime(iso: string | null) {
  if (!iso) return '-'
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function stintDurMs(s: StintStat): number | null {
  if (s.started_at && s.ended_at)
    return new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()
  if (s.lap_count && s.avg_lap_ms) return s.lap_count * s.avg_lap_ms
  return null
}

const KART_Q_COLORS: Record<string, string> = {
  ROCKET: 'text-purple-400', FAST: 'text-green-400', MEDIUM: 'text-gray-400',
  BAD: 'text-red-400', UNKNOWN: 'text-gray-600',
}
const KART_Q_LABELS: Record<string, string> = {
  ROCKET: '🚀', FAST: 'Bon', MEDIUM: '—', BAD: 'Mauvais', UNKNOWN: '—',
}
const KART_Q_ORDER = ['ROCKET', 'FAST', 'MEDIUM', 'UNKNOWN', 'BAD']

const LEVEL_COLORS: Record<string, string> = {
  ELITE: 'text-purple-400', FAST: 'text-blue-400',
  MEDIUM: 'text-yellow-400', SLOW: 'text-red-400', UNKNOWN: 'text-gray-600',
}

// ── sort / filter primitives ───────────────────────────────────────────────

type Sort = { col: string; dir: 'asc' | 'desc' }

function useSort(defaultCol: string, defaultDir: 'asc' | 'desc' = 'desc') {
  const [sort, setSort] = useState<Sort>({ col: defaultCol, dir: defaultDir })
  const toggle = (col: string) =>
    setSort(prev => prev.col === col ? { col, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'desc' })
  return { sort, toggle }
}

function applySort<T>(items: T[], sort: Sort, getVal: (item: T, col: string) => string | number | null): T[] {
  return [...items].sort((a, b) => {
    const av = getVal(a, sort.col), bv = getVal(b, sort.col)
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
    return sort.dir === 'asc' ? cmp : -cmp
  })
}

function Hdr({ col, label, sort, onSort, right = false, className }: {
  col: string; label: string; sort: Sort; onSort: (c: string) => void; right?: boolean; className?: string
}) {
  const active = sort.col === col
  return (
    <button onClick={() => onSort(col)}
      className={clsx('flex items-center gap-0.5 text-xs font-medium transition-colors', className,
        right && 'justify-end w-full',
        active ? 'text-orange-400' : 'text-gray-500 hover:text-gray-300')}>
      {label}{active && <span className="ml-0.5">{sort.dir === 'asc' ? '↑' : '↓'}</span>}
    </button>
  )
}

function FilterBar({ value, onChange, placeholder = 'Filtrer…', className }: {
  value: string; onChange: (v: string) => void; placeholder?: string; className?: string
}) {
  return (
    <div className={clsx('relative', className)}>
      <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-600 pointer-events-none" />
      <input
        className="w-full bg-gray-800/60 border border-gray-700 rounded pl-6 pr-6 py-1 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-orange-500"
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
      />
      {value && (
        <button onClick={() => onChange('')} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-600 hover:text-white">
          <X size={10} />
        </button>
      )}
    </div>
  )
}

// ── StintRow ───────────────────────────────────────────────────────────────

const STINT_COLS = 'grid-cols-[22px_minmax(0,120px)_44px_48px_58px_36px_60px_60px_60px]'

function StintRow({ s, idx }: { s: StintStat; idx: number }) {
  return (
    <div className={clsx('px-3 py-1.5 text-xs grid gap-2', STINT_COLS,
      idx % 2 === 0 ? 'bg-gray-800/40' : 'bg-gray-800/20')}>
      <span className="text-gray-600 text-right self-center">{s.stint_number}</span>
      <span className="text-white font-medium truncate self-center">{s.driver_name || <span className="text-gray-600 italic">—</span>}</span>
      <span className={clsx('text-right font-bold self-center', LEVEL_COLORS[s.level ?? 'UNKNOWN'])}>
        {s.level && s.level !== 'UNKNOWN' ? s.level.slice(0, 4) : '—'}
      </span>
      <span className="text-right font-mono text-gray-500 self-center">{fmtTime(s.started_at)}</span>
      <span className="text-right font-mono text-gray-400 self-center">{fmtDur(stintDurMs(s))}</span>
      <span className="text-right text-gray-300 self-center">{s.lap_count}</span>
      <span className="text-right font-mono text-yellow-300 self-center">{fmtMs(s.best_lap_ms ?? 0)}</span>
      <span className="text-right font-mono text-gray-400 self-center">{fmtMs(s.avg_lap_ms ?? 0)}</span>
      <span className={clsx('text-right self-center', KART_Q_COLORS[s.kart_quality])}>{KART_Q_LABELS[s.kart_quality]}</span>
    </div>
  )
}

// ── EntryPanel ─────────────────────────────────────────────────────────────

interface PilotAgg {
  driver_name: string
  stint_count: number
  total_laps: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  avg_std_dev_ms: number | null
  best_quality: string
}

function EntryPanel({ entryId }: { entryId: number }) {
  const navigate = useNavigate()
  const [detail, setDetail] = useState<EntryDetail | null>(null)
  const [view, setView] = useState<'pilots' | 'stints'>('pilots')
  const [filter, setFilter] = useState('')
  const stintSort = useSort('stint_number', 'asc')
  const pilotSort = useSort('total_laps', 'desc')

  useEffect(() => { api.stats.entry(entryId).then(setDetail).catch(() => {}) }, [entryId])

  const pilotAgg = useMemo<PilotAgg[]>(() => {
    if (!detail) return []
    const map: Record<string, PilotAgg> = {}
    for (const s of detail.stints) {
      const key = s.driver_name || '—'
      if (!map[key]) map[key] = { driver_name: key, stint_count: 0, total_laps: 0, best_lap_ms: null, avg_lap_ms: null, avg_std_dev_ms: null, best_quality: 'UNKNOWN' }
      const p = map[key]
      p.stint_count++
      p.total_laps += s.lap_count
      if (s.best_lap_ms != null && (p.best_lap_ms == null || s.best_lap_ms < p.best_lap_ms)) p.best_lap_ms = s.best_lap_ms
      if (KART_Q_ORDER.indexOf(s.kart_quality) < KART_Q_ORDER.indexOf(p.best_quality)) p.best_quality = s.kart_quality
    }
    for (const key of Object.keys(map)) {
      const stints = detail.stints.filter(s => (s.driver_name || '—') === key && s.lap_count >= 3)
      if (stints.length) {
        const total = stints.reduce((a, s) => a + s.lap_count, 0)
        const withAvg = stints.filter(s => s.avg_lap_ms != null)
        if (withAvg.length) map[key].avg_lap_ms = Math.round(withAvg.reduce((a, s) => a + s.avg_lap_ms! * s.lap_count, 0) / withAvg.reduce((a, s) => a + s.lap_count, 0))
        const withStd = stints.filter(s => s.std_dev_ms != null)
        if (withStd.length) map[key].avg_std_dev_ms = Math.round(withStd.reduce((a, s) => a + s.std_dev_ms! * s.lap_count, 0) / total)
      }
    }
    return Object.values(map)
  }, [detail])

  const pilotMedian = useMemo(() => median(pilotAgg.map(p => p.avg_lap_ms).filter((v): v is number => v != null)), [pilotAgg])

  function pilotRating(p: PilotAgg) {
    return {
      speed: speedStars(p.avg_lap_ms, pilotMedian),
      consistency: consistencyStars(p.avg_std_dev_ms, p.avg_lap_ms),
    }
  }

  const visibleStints = useMemo(() => {
    const q = filter.toLowerCase()
    let rows = (detail?.stints ?? []).filter(s => s.lap_count > 0)
    if (q) rows = rows.filter(s => (s.driver_name || '').toLowerCase().includes(q))
    return applySort(rows, stintSort.sort, (s, col) => {
      if (col === 'stint_number') return s.stint_number
      if (col === 'driver_name') return s.driver_name || ''
      if (col === 'started_at') return s.started_at || ''
      if (col === 'duration') return stintDurMs(s)
      if (col === 'lap_count') return s.lap_count
      if (col === 'best_lap_ms') return s.best_lap_ms
      if (col === 'avg_lap_ms') return s.avg_lap_ms
      return null
    })
  }, [detail, filter, stintSort.sort])

  const visiblePilots = useMemo(() => {
    const q = filter.toLowerCase()
    let rows = pilotAgg
    if (q) rows = rows.filter(p => p.driver_name.toLowerCase().includes(q))
    return applySort(rows, pilotSort.sort, (p, col) => {
      if (col === 'driver_name') return p.driver_name
      if (col === 'stint_count') return p.stint_count
      if (col === 'total_laps') return p.total_laps
      if (col === 'best_lap_ms') return p.best_lap_ms
      if (col === 'avg_lap_ms') return p.avg_lap_ms
      if (col === 'stars') { const r = pilotRating(p); return globalScore(r.speed, r.consistency) }
      return null
    })
  }, [pilotAgg, filter, pilotSort.sort, pilotMedian])

  if (!detail) return <div className="p-3 text-xs text-gray-500 animate-pulse">Chargement…</div>

  const PILOT_COLS = 'grid-cols-[minmax(0,150px)_40px_40px_60px_60px_42px_105px]'

  return (
    <div className="border-t border-gray-700">
      <div className="flex items-center gap-2 px-3 pt-2 pb-1">
        {(['pilots', 'stints'] as const).map(v => (
          <button key={v} onClick={() => { setView(v); setFilter('') }}
            className={clsx('px-2.5 py-0.5 rounded text-xs font-medium transition-colors',
              view === v ? 'bg-orange-500/20 text-orange-400' : 'text-gray-500 hover:text-white')}>
            {v === 'pilots' ? 'Pilotes' : 'Stints'}
          </button>
        ))}
        <FilterBar value={filter} onChange={setFilter} placeholder="Filtrer pilote…" className="flex-1 max-w-xs" />
      </div>

      {view === 'stints' && (
        <>
          <div className={clsx('px-3 py-1 grid gap-2', STINT_COLS)}>
            <Hdr col="stint_number" label="#" sort={stintSort.sort} onSort={stintSort.toggle} right />
            <Hdr col="driver_name" label="Pilote" sort={stintSort.sort} onSort={stintSort.toggle} />
            <span className="text-right text-xs text-gray-500 font-medium">Niv.</span>
            <Hdr col="started_at" label="Heure" sort={stintSort.sort} onSort={stintSort.toggle} right />
            <Hdr col="duration" label="Durée" sort={stintSort.sort} onSort={stintSort.toggle} right />
            <Hdr col="lap_count" label="T." sort={stintSort.sort} onSort={stintSort.toggle} right />
            <Hdr col="best_lap_ms" label="Best" sort={stintSort.sort} onSort={stintSort.toggle} right />
            <Hdr col="avg_lap_ms" label="Moy." sort={stintSort.sort} onSort={stintSort.toggle} right />
            <span className="text-right text-xs text-gray-500 font-medium">Kart</span>
          </div>
          {visibleStints.map((s, i) => <StintRow key={s.id} s={s} idx={i} />)}
          {visibleStints.length === 0 && <p className="px-3 py-2 text-xs text-gray-600">Aucun résultat.</p>}
        </>
      )}

      {view === 'pilots' && (
        <>
          <div className={clsx('px-3 py-1 grid gap-2', PILOT_COLS)}>
            <Hdr col="driver_name" label="Pilote" sort={pilotSort.sort} onSort={pilotSort.toggle} />
            <Hdr col="stint_count" label="St." sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="total_laps" label="T." sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="best_lap_ms" label="Best" sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="avg_lap_ms" label="Moy." sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="cv" label="σ%" sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="stars" label="Niveau" sort={pilotSort.sort} onSort={pilotSort.toggle} right />
          </div>
          {visiblePilots.map((p, i) => {
            const r = pilotRating(p)
            return (
              <div key={p.driver_name} className={clsx('px-3 py-1.5 grid gap-2 text-xs', PILOT_COLS,
                i % 2 === 0 ? 'bg-gray-800/40' : 'bg-gray-800/20')}>
                <button onClick={() => navigate(`/stats/pilot/${encodeURIComponent(p.driver_name)}`)}
                  className="text-white font-medium truncate self-center text-left hover:text-orange-300 transition-colors">
                  {p.driver_name}
                </button>
                <span className="text-right text-gray-500 self-center">{p.stint_count}</span>
                <span className="text-right text-gray-300 font-medium self-center">{p.total_laps}</span>
                <span className="text-right font-mono text-yellow-300 self-center">{fmtMs(p.best_lap_ms ?? 0)}</span>
                <span className="text-right font-mono text-gray-400 self-center">{fmtMs(p.avg_lap_ms ?? 0)}</span>
                <span className="text-right font-mono text-blue-300/70 self-center">{fmtCV(p.avg_std_dev_ms, p.avg_lap_ms)}</span>
                <div className="self-center"><RatingCell speed={r.speed} consistency={r.consistency} /></div>
              </div>
            )
          })}
          {visiblePilots.length === 0 && <p className="px-3 py-2 text-xs text-gray-600">Aucun résultat.</p>}
        </>
      )}
    </div>
  )
}

// ── EventPanel ─────────────────────────────────────────────────────────────

function EventPanel({ eventId }: { eventId: number }) {
  const navigate = useNavigate()
  const [data, setData]     = useState<EventStatsResponse | null>(null)
  const [pilots, setPilots] = useState<PilotStat[]>([])
  const [tab, setTab]       = useState<'teams' | 'pilots'>('teams')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [teamFilter, setTeamFilter] = useState('')
  const [pilotFilter, setPilotFilter] = useState('')
  const teamSort  = useSort('total_laps', 'desc')
  const pilotSort = useSort('total_laps', 'desc')

  useEffect(() => {
    setData(null); setExpanded(null)
    api.stats.event(eventId).then(setData).catch(() => {})
    api.stats.pilots(eventId).then(r => setPilots(r.pilots)).catch(() => {})
  }, [eventId])

  const visibleTeams = useMemo(() => {
    const q = teamFilter.toLowerCase()
    let rows = data?.entries ?? []
    if (q) rows = rows.filter(e => e.team_name.toLowerCase().includes(q) || e.bib.toLowerCase().includes(q))
    return applySort(rows, teamSort.sort, (e, col) => {
      if (col === 'rank') return data?.entries.indexOf(e) ?? 0
      if (col === 'team_name') return e.team_name
      if (col === 'bib') return e.bib
      if (col === 'total_laps') return e.total_laps
      if (col === 'best_lap_ms') return e.best_lap_ms
      if (col === 'avg_lap_ms') return e.avg_lap_ms
      if (col === 'pit_count') return e.pit_count
      if (col === 'stars') { const med = median(data?.entries.map(x => x.avg_lap_ms).filter((v): v is number => v != null) ?? []); return globalScore(speedStars(e.avg_lap_ms, med), consistencyStars(e.avg_std_dev_ms, e.avg_lap_ms)) }
      return null
    })
  }, [data, teamFilter, teamSort.sort])

  const pMedian = useMemo(() => median(pilots.map(p => p.avg_lap_ms).filter((v): v is number => v != null)), [pilots])

  const visiblePilots = useMemo(() => {
    const q = pilotFilter.toLowerCase()
    let rows = pilots
    if (q) rows = rows.filter(p => p.driver_name.toLowerCase().includes(q) || p.teams.toLowerCase().includes(q))
    return applySort(rows, pilotSort.sort, (p, col) => {
      if (col === 'driver_name') return p.driver_name
      if (col === 'stint_count') return p.stint_count
      if (col === 'total_laps') return p.total_laps
      if (col === 'best_lap_ms') return p.best_lap_ms
      if (col === 'avg_lap_ms') return p.avg_lap_ms
      if (col === 'stars') { const r = { speed: speedStars(p.avg_lap_ms, pMedian), consistency: consistencyStars(p.avg_std_dev_ms, p.avg_lap_ms) }; return globalScore(r.speed, r.consistency) }
      if (col === 'cv') return p.avg_std_dev_ms != null && p.avg_lap_ms ? p.avg_std_dev_ms / p.avg_lap_ms * 100 : null
      return null
    })
  }, [pilots, pilotFilter, pilotSort.sort, pMedian])

  const teamMedian = useMemo(() => median(data?.entries.map(e => e.avg_lap_ms).filter((v): v is number => v != null) ?? []), [data])

  if (!data) return <div className="p-4 text-sm text-gray-500 animate-pulse">Chargement…</div>

  const TEAM_COLS = 'grid-cols-[28px_minmax(0,170px)_50px_45px_65px_65px_40px_105px_32px]'
  const PCOLS = 'grid-cols-[minmax(0,160px)_40px_40px_65px_65px_42px_105px]'

  return (
    <div className="space-y-2">
      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800 pb-0">
        {(['teams', 'pilots'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={clsx('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              tab === t ? 'border-orange-500 text-orange-400' : 'border-transparent text-gray-400 hover:text-white')}>
            {t === 'teams' ? <><Users size={13} className="inline mr-1" />Équipes</> : <><Flag size={13} className="inline mr-1" />Pilotes</>}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-600 self-center pr-2">{data.entries.length} équipes</span>
      </div>

      {/* Teams tab */}
      {tab === 'teams' && (
        <div className="rounded-lg border border-gray-800 overflow-hidden">
          <div className="px-3 py-1.5 bg-gray-800/40 border-b border-gray-800">
            <FilterBar value={teamFilter} onChange={setTeamFilter} placeholder="Filtrer équipe / bib…" />
          </div>
          <div className={clsx('grid gap-2 px-3 py-1.5 bg-gray-800/60', TEAM_COLS)}>
            <Hdr col="rank" label="#" sort={teamSort.sort} onSort={teamSort.toggle} right />
            <Hdr col="team_name" label="Équipe" sort={teamSort.sort} onSort={teamSort.toggle} />
            <Hdr col="bib" label="Bib" sort={teamSort.sort} onSort={teamSort.toggle} right />
            <Hdr col="total_laps" label="T." sort={teamSort.sort} onSort={teamSort.toggle} right />
            <Hdr col="best_lap_ms" label="Best" sort={teamSort.sort} onSort={teamSort.toggle} right />
            <Hdr col="avg_lap_ms" label="Moy." sort={teamSort.sort} onSort={teamSort.toggle} right />
            <Hdr col="pit_count" label="Pit" sort={teamSort.sort} onSort={teamSort.toggle} right />
            <Hdr col="stars" label="Niveau" sort={teamSort.sort} onSort={teamSort.toggle} right />
            <span />
          </div>
          {visibleTeams.map((e, i) => {
            const tSpeed = speedStars(e.avg_lap_ms, teamMedian)
            const tCons  = consistencyStars(e.avg_std_dev_ms, e.avg_lap_ms)
            return (
              <div key={e.id} className="border-t border-gray-800/60">
                <button
                  onClick={() => setExpanded(expanded === e.id ? null : e.id)}
                  className={clsx('w-full grid gap-2 px-3 py-2 text-sm text-left transition-colors hover:bg-gray-800/50', TEAM_COLS,
                    expanded === e.id && 'bg-gray-800/60')}>
                  <span className="text-gray-500 text-xs text-right self-center">{i + 1}</span>
                  <span className="font-medium text-white truncate">{e.team_name}</span>
                  <span className="text-right text-gray-400 font-mono text-xs self-center">{e.bib}</span>
                  <span className="text-right font-bold text-white self-center">{e.total_laps}</span>
                  <span className="text-right font-mono text-yellow-300 text-xs self-center">{fmtMs(e.best_lap_ms ?? 0)}</span>
                  <span className="text-right font-mono text-gray-400 text-xs self-center">{fmtMs(e.avg_lap_ms ?? 0)}</span>
                  <span className="text-right text-gray-400 text-xs self-center">{e.pit_count}</span>
                  <div className="self-center"><RatingCell speed={tSpeed} consistency={tCons} /></div>
                  <span className="text-gray-500 self-center justify-self-center">
                    {expanded === e.id ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  </span>
                </button>
                {expanded === e.id && <EntryPanel entryId={e.id} />}
              </div>
            )
          })}
          {visibleTeams.length === 0 && <p className="px-3 py-3 text-sm text-gray-600">Aucun résultat.</p>}
        </div>
      )}

      {/* Pilots tab */}
      {tab === 'pilots' && (
        <div className="rounded-lg border border-gray-800 overflow-hidden">
          <div className="px-3 py-1.5 bg-gray-800/40 border-b border-gray-800">
            <FilterBar value={pilotFilter} onChange={setPilotFilter} placeholder="Filtrer pilote / équipe…" />
          </div>
          <div className={clsx('grid gap-2 px-3 py-1.5 bg-gray-800/60', PCOLS)}>
            <Hdr col="driver_name" label="Pilote · Équipe" sort={pilotSort.sort} onSort={pilotSort.toggle} />
            <Hdr col="stint_count" label="St." sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="total_laps" label="T." sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="best_lap_ms" label="Best" sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="avg_lap_ms" label="Moy." sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="cv" label="σ%" sort={pilotSort.sort} onSort={pilotSort.toggle} right />
            <Hdr col="stars" label="Niveau" sort={pilotSort.sort} onSort={pilotSort.toggle} right />
          </div>
          {visiblePilots.map((p, i) => {
            const r = { speed: speedStars(p.avg_lap_ms, pMedian), consistency: consistencyStars(p.avg_std_dev_ms, p.avg_lap_ms) }
            return (
              <div key={p.driver_name + i} className={clsx('grid gap-2 px-3 py-2 text-sm border-t border-gray-800/60', PCOLS,
                i % 2 === 0 ? 'bg-gray-900' : 'bg-gray-900/50')}>
                <div className="min-w-0">
                  <button onClick={() => navigate(`/stats/pilot/${encodeURIComponent(p.driver_name)}`)}
                    className="font-medium text-white hover:text-orange-300 transition-colors">
                    {p.driver_name}
                  </button>
                  <span className="text-xs text-gray-500 ml-2">{p.teams}</span>
                </div>
                <span className="text-right text-gray-400 text-xs self-center">{p.stint_count}</span>
                <span className="text-right font-bold text-white self-center">{p.total_laps}</span>
                <span className="text-right font-mono text-yellow-300 text-xs self-center">{fmtMs(p.best_lap_ms ?? 0)}</span>
                <span className="text-right font-mono text-gray-400 text-xs self-center">{fmtMs(p.avg_lap_ms ?? 0)}</span>
                <span className="text-right font-mono text-blue-300/70 text-xs self-center">{fmtCV(p.avg_std_dev_ms, p.avg_lap_ms)}</span>
                <div className="self-center"><RatingCell speed={r.speed} consistency={r.consistency} /></div>
              </div>
            )
          })}
          {visiblePilots.length === 0 && <p className="px-3 py-4 text-sm text-gray-600">Aucun résultat.</p>}
        </div>
      )}
    </div>
  )
}

// ── Main Stats page ────────────────────────────────────────────────────────

export function Stats() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [events, setEvents]       = useState<KartingEvent[]>([])
  const [circuits, setCircuits]   = useState<Circuit[]>([])
  const [circuitFilter, setCircuitFilter] = useState<string>('all')
  const [eventFilter, setEventFilter]     = useState('')
  const { viewedEventId } = useEventView()
  const [selectedEvent, setSelectedEvent] = useState<number | null>(
    viewedEventId ?? (searchParams.get('event') ? Number(searchParams.get('event')) : null)
  )

  useEffect(() => {
    if (viewedEventId) setSelectedEvent(viewedEventId)
  }, [viewedEventId])
  const [search, setSearch]       = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [activeEventId, setActiveEventId] = useState<number | null>(null)
  const eventSort = useSort('event_date', 'desc')

  useEffect(() => {
    Promise.all([api.events.list(), api.circuits.list()]).then(([evs, cirs]) => {
      setEvents(evs.events)
      setCircuits(cirs.circuits.filter((c: Circuit) => c.id != null))
      const active = evs.events.find((e: KartingEvent) => e.is_active)
      if (active) setActiveEventId(active.id)
    }).catch(() => {})
  }, [])

  const doSearch = useCallback((q: string) => {
    if (q.length < 2) { setSearchResults([]); return }
    setSearchLoading(true)
    api.stats.search(q).then(r => setSearchResults(r.results)).catch(() => {}).finally(() => setSearchLoading(false))
  }, [])

  useEffect(() => {
    const t = setTimeout(() => doSearch(search), 300)
    return () => clearTimeout(t)
  }, [search, doSearch])

  const filteredEvents = useMemo(() => {
    const q = eventFilter.toLowerCase()
    let rows = events.filter(e => {
      if (circuitFilter !== 'all' && e.circuit_url !== circuitFilter) return false
      return e.source === 'proxy' || !e.is_active
    })
    if (q) rows = rows.filter(e => e.name.toLowerCase().includes(q))
    return applySort(rows, eventSort.sort, (e, col) => {
      if (col === 'name') return e.name
      if (col === 'event_date') return e.event_date || ''
      if (col === 'duration_hours') return e.duration_hours
      return null
    })
  }, [events, circuitFilter, eventFilter, eventSort.sort])

  return (
    <div className="space-y-6 max-w-4xl">
      <h1 className="text-lg font-bold text-white flex items-center gap-2">
        <Trophy size={18} className="text-orange-400" /> Statistiques
      </h1>

      {/* ── Événement en cours ─────────────────────────────────────── */}
      {activeEventId && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-green-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse inline-block" />
            Événement en cours
          </h2>
          <EventPanel eventId={activeEventId} />
        </section>
      )}

      {/* ── Recherche ─────────────────────────────────────────────── */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-1.5">
          <Search size={14} /> Recherche équipe / pilote
        </h2>
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            className="w-full bg-gray-900 border border-gray-700 rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-orange-500"
            placeholder="Nom d'équipe ou pilote…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        {searchLoading && <p className="text-xs text-gray-500 animate-pulse">Recherche…</p>}
        {searchResults.length > 0 && (
          <div className="rounded-lg border border-gray-800 overflow-hidden">
            {searchResults.map((r, i) => (
              <button key={i}
                onClick={() => {
                  setSearch(''); setSearchResults([])
                  if (r.match_type === 'pilot' && r.driver_name) {
                    navigate(`/stats/pilot/${encodeURIComponent(r.driver_name)}`)
                  } else {
                    navigate(`/stats/team/${encodeURIComponent(r.team_name)}`)
                  }
                }}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-left border-t border-gray-800 first:border-t-0 hover:bg-gray-800/50 transition-colors">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-white truncate">{r.team_name}</p>
                  {r.driver_name && <p className="text-xs text-orange-400 flex items-center gap-1"><Flag size={10} /> {r.driver_name}</p>}
                  <p className="text-xs text-gray-500">{r.event_name}</p>
                </div>
                <div className="text-right shrink-0 text-xs text-gray-400 space-y-0.5">
                  <p className="font-bold text-white">{r.total_laps} tours</p>
                  <p className="font-mono text-yellow-300">{fmtMs(r.best_lap_ms ?? 0)}</p>
                </div>
              </button>
            ))}
          </div>
        )}

      </section>

      {/* ── Historique ────────────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-1.5">
            <Clock size={14} /> Historique
          </h2>
          <select
            className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-orange-500"
            value={circuitFilter}
            onChange={e => setCircuitFilter(e.target.value)}>
            <option value="all">Tous les circuits</option>
            {circuits.map(c => <option key={c.id} value={c.circuit_url}>{c.name}</option>)}
          </select>
          <FilterBar value={eventFilter} onChange={setEventFilter} placeholder="Filtrer événement…" className="flex-1 min-w-[160px] max-w-xs" />
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <span>Trier :</span>
            {(['event_date', 'name', 'duration_hours'] as const).map(col => (
              <button key={col} onClick={() => eventSort.toggle(col)}
                className={clsx('px-1.5 py-0.5 rounded transition-colors',
                  eventSort.sort.col === col ? 'text-orange-400 bg-orange-500/10' : 'hover:text-white')}>
                {col === 'event_date' ? 'Date' : col === 'name' ? 'Nom' : 'Durée'}
                {eventSort.sort.col === col && <span className="ml-0.5">{eventSort.sort.dir === 'asc' ? '↑' : '↓'}</span>}
              </button>
            ))}
          </div>
        </div>

        {filteredEvents.length === 0 && (
          <p className="text-sm text-gray-600">Aucun événement importé.</p>
        )}

        <div className="space-y-2">
          {filteredEvents.map(ev => (
            <div key={ev.id} className={clsx(
              'rounded-lg border transition-colors',
              selectedEvent === ev.id ? 'border-orange-700/60 bg-gray-900' : 'border-gray-800 bg-gray-900/50'
            )}>
              <button
                onClick={() => setSelectedEvent(selectedEvent === ev.id ? null : ev.id)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-white text-sm">{ev.name}</p>
                  <p className="text-xs text-gray-500">
                    {ev.duration_hours}h
                    {ev.event_date && ` · ${new Date(ev.event_date).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })}`}
                  </p>
                </div>
                {selectedEvent === ev.id
                  ? <ChevronDown size={15} className="text-gray-400 shrink-0" />
                  : <ChevronRight size={15} className="text-gray-400 shrink-0" />}
              </button>
              {selectedEvent === ev.id && (
                <div className="border-t border-gray-800 px-4 py-3">
                  <EventPanel eventId={ev.id} />
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
