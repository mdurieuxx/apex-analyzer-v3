import { useState, useEffect, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import { Search } from 'lucide-react'
import { api } from '../api/client'
import { useEventView } from '../hooks/useEventView'
import { HistoricalStandings } from '../components/HistoricalStandings'
import type { TeamPerformance, TeamLevel, KartQuality, StintDetail, DriverPerformance } from '../types'

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtMs(ms: number | null): string {
  if (!ms || ms <= 0) return '—'
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  const d = Math.floor((ms % 1000) / 100)
  return `${m}:${String(s).padStart(2, '0')}.${d}`
}

function fmtCV(std_ms: number, avg_ms: number): string {
  if (!std_ms || !avg_ms) return '—'
  return (std_ms / avg_ms * 100).toFixed(1) + '%'
}

function fmtDelta(pct: number | null): React.ReactNode {
  if (pct === null) return <span className="text-gray-600">—</span>
  const cls = pct < -1 ? 'text-green-400' : pct > 2 ? 'text-red-400' : 'text-gray-300'
  return <span className={cls}>{pct > 0 ? '+' : ''}{pct.toFixed(2)}%</span>
}

// ── Badges ────────────────────────────────────────────────────────────────────

const LEVEL_STYLES: Record<TeamLevel, string> = {
  ELITE:   'bg-purple-500/20 text-purple-300 border-purple-500/40',
  FAST:    'bg-blue-500/20   text-blue-300   border-blue-500/40',
  MEDIUM:  'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
  SLOW:    'bg-red-500/20    text-red-300    border-red-500/40',
  UNKNOWN: 'bg-gray-700/40   text-gray-500   border-gray-600/50',
}

const LEVEL_ICONS: Record<TeamLevel, string> = {
  ELITE: '🥇', FAST: '🥈', MEDIUM: '🥉', SLOW: '🐢', UNKNOWN: '⚪',
}

const QUALITY_STYLES: Record<KartQuality, string> = {
  ROCKET:  'bg-purple-500/20 text-purple-300 border-purple-500/40',
  FAST:    'bg-green-500/20  text-green-400  border-green-500/40',
  MEDIUM:  'bg-orange-500/20 text-orange-400 border-orange-500/40',
  BAD:     'bg-red-500/20    text-red-400    border-red-500/40',
  UNKNOWN: 'bg-gray-800/40   text-gray-600   border-gray-700/40',
}

const QUALITY_ICONS: Record<KartQuality, string> = {
  ROCKET: '🚀', FAST: '🟢', MEDIUM: '🟠', BAD: '🔴', UNKNOWN: '❓',
}

function LevelBadge({ level }: { level: TeamLevel }) {
  return (
    <span className={clsx('inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-xs font-bold', LEVEL_STYLES[level])}>
      {LEVEL_ICONS[level]} {level}
    </span>
  )
}

function QualityBadge({ quality, score }: { quality: KartQuality; score: number | null }) {
  return (
    <span
      className={clsx('inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-xs font-semibold', QUALITY_STYLES[quality])}
      title={score !== null ? `Score: ${score > 0 ? '+' : ''}${score.toFixed(2)}%` : ''}
    >
      {QUALITY_ICONS[quality]} {quality}
      {score !== null && <span className="opacity-60">{score > 0 ? '+' : ''}{score.toFixed(1)}%</span>}
    </span>
  )
}

// ── Stint detail rows ─────────────────────────────────────────────────────────

const SMALL_LEVEL_STYLES: Record<string, string> = {
  ELITE:   'text-purple-400',
  FAST:    'text-blue-400',
  MEDIUM:  'text-yellow-400',
  SLOW:    'text-red-400',
  UNKNOWN: 'text-gray-600',
}

const STINT_KART_STYLES: Record<string, string> = {
  GOOD:    'text-green-400',
  NEUTRAL: 'text-gray-500',
  BAD:     'text-red-400',
  UNKNOWN: 'text-gray-700',
}
const STINT_KART_LABELS: Record<string, string> = {
  GOOD: 'Bon', NEUTRAL: '—', BAD: 'Mauvais', UNKNOWN: '—',
}

function fmtTime(iso: string | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function StintRows({ stints }: { stints: StintDetail[] }) {
  if (!stints.length) return (
    <tr className="bg-gray-900/60">
      <td colSpan={10} className="px-6 py-2 text-xs text-gray-600 italic">Aucun stint enregistré</td>
    </tr>
  )
  return (
    <>
      {stints.map((s, i) => (
        <tr key={i} className={clsx('text-xs border-t border-gray-800/60', s.is_current ? 'bg-blue-950/20' : 'bg-gray-900/40')}>
          <td className="pl-8 pr-2 py-1.5 text-gray-400">
            {s.is_current
              ? <span className="text-blue-400 font-medium">▶ en cours</span>
              : <span className="text-gray-600">#{i + 1}</span>}
          </td>
          <td className="px-2 py-1.5 text-gray-500 font-mono tabular-nums">{fmtTime(s.started_at)}</td>
          <td className="px-2 py-1.5 text-gray-300 max-w-[120px] truncate" title={s.driver}>
            {s.driver.startsWith('relay_') ? <span className="text-gray-600 italic">?</span> : s.driver}
          </td>
          <td className="px-2 py-1.5 text-center">
            <span className={clsx('font-bold', SMALL_LEVEL_STYLES[s.level ?? 'UNKNOWN'] ?? 'text-gray-600')}>
              {s.level && s.level !== 'UNKNOWN' ? s.level : '—'}
            </span>
          </td>
          <td className="px-2 py-1.5 text-center">
            <span className={clsx('font-medium', STINT_KART_STYLES[s.kart_quality ?? 'UNKNOWN'] ?? 'text-gray-700')}>
              {STINT_KART_LABELS[s.kart_quality ?? 'UNKNOWN'] ?? '—'}
            </span>
          </td>
          <td className="px-2 py-1.5 text-center text-gray-400">{s.total_laps_ms || '—'}</td>
          <td className="px-2 py-1.5 text-center font-mono text-gray-300">{fmtMs(s.avg_ms)}</td>
          <td className="px-2 py-1.5 text-center font-mono text-green-400">{fmtMs(s.best_ms)}</td>
          <td className="px-2 py-1.5 text-center font-mono text-gray-400">{fmtCV(s.std_ms, s.avg_ms)}</td>
          <td className="px-2 py-1.5 text-center font-mono">{fmtDelta(s.delta_pct)}</td>
        </tr>
      ))}
    </>
  )
}

// ── Sort helper ───────────────────────────────────────────────────────────────

type SortKey = 'level' | 'delta' | 'stints' | 'laps' | 'kart'
const LEVEL_ORDER: Record<string, number> = { ELITE: 0, FAST: 1, MEDIUM: 2, SLOW: 3, UNKNOWN: 4 }

function sortTeams(teams: TeamPerformance[], key: SortKey, dir: 1 | -1): TeamPerformance[] {
  return [...teams].sort((a, b) => {
    let v = 0
    if (key === 'level')  v = (LEVEL_ORDER[a.team_level] ?? 4) - (LEVEL_ORDER[b.team_level] ?? 4)
    if (key === 'delta')  v = ((a.current_delta_pct ?? 99) - (b.current_delta_pct ?? 99))
    if (key === 'stints') v = b.completed_stints - a.completed_stints
    if (key === 'laps')   v = b.current_stint_laps - a.current_stint_laps
    if (key === 'kart') {
      const qo: Record<string, number> = { ROCKET: 0, FAST: 1, MEDIUM: 2, BAD: 3, UNKNOWN: 4 }
      v = (qo[a.kart_quality] ?? 4) - (qo[b.kart_quality] ?? 4)
    }
    return v * dir
  })
}

function SortTh({ label, sk, cur, dir, onClick }: {
  label: string; sk: SortKey; cur: SortKey; dir: 1 | -1; onClick: (k: SortKey) => void
}) {
  const active = sk === cur
  return (
    <th
      className="px-3 py-2 text-center cursor-pointer select-none hover:text-white transition-colors"
      onClick={() => onClick(sk)}
    >
      {label}{active ? (dir === 1 ? ' ↑' : ' ↓') : ''}
    </th>
  )
}

// ── Teams tab ─────────────────────────────────────────────────────────────────

const ALL_LEVELS: TeamLevel[] = ['ELITE', 'FAST', 'MEDIUM', 'SLOW']
const ALL_QUALITIES: KartQuality[] = ['ROCKET', 'FAST', 'MEDIUM', 'BAD']

function TeamsTab({ teams, search, initialExpanded }: { teams: TeamPerformance[]; search: string; initialExpanded?: string }) {
  const [levelFilter, setLevelFilter] = useState<TeamLevel | null>(null)
  const [qualityFilter, setQualityFilter] = useState<KartQuality | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('level')
  const [sortDir, setSortDir] = useState<1 | -1>(1)
  const [expanded, setExpanded] = useState<string | null>(initialExpanded ?? null)
  const [dbStints, setDbStints] = useState<Record<string, StintDetail[]>>({})

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir(d => d === 1 ? -1 : 1)
    else { setSortKey(k); setSortDir(1) }
  }

  function toggleExpand(teamId: string) {
    const next = expanded === teamId ? null : teamId
    setExpanded(next)
    if (next && !(teamId in dbStints)) {
      api.perfTeamStints(teamId)
        .then(r => setDbStints(prev => ({ ...prev, [teamId]: r.stints })))
        .catch(() => setDbStints(prev => ({ ...prev, [teamId]: [] })))
    }
  }

  const display = useMemo(() => {
    let r = teams
    if (levelFilter)   r = r.filter(t => t.team_level === levelFilter)
    if (qualityFilter) r = r.filter(t => t.kart_quality === qualityFilter)
    if (search) {
      const q = search.toLowerCase()
      r = r.filter(t => (t.team_name || t.team_id).toLowerCase().includes(q))
    }
    return sortTeams(r, sortKey, sortDir)
  }, [teams, levelFilter, qualityFilter, search, sortKey, sortDir])

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-gray-500 mr-1">Niveau:</span>
        <button
          onClick={() => setLevelFilter(null)}
          className={clsx('px-2 py-0.5 rounded-full text-xs border transition-colors',
            !levelFilter ? 'bg-gray-600 text-white border-gray-500' : 'text-gray-400 border-gray-700 hover:border-gray-500')}
        >Tous</button>
        {ALL_LEVELS.map(l => (
          <button key={l} onClick={() => setLevelFilter(levelFilter === l ? null : l)}
            className={clsx('px-2 py-0.5 rounded-full text-xs border transition-colors',
              levelFilter === l ? LEVEL_STYLES[l] + ' font-bold' : 'text-gray-400 border-gray-700 hover:border-gray-500')}>
            {LEVEL_ICONS[l]} {l} <span className="opacity-60">({teams.filter(t => t.team_level === l).length})</span>
          </button>
        ))}
        <span className="text-xs text-gray-500 ml-3 mr-1">Kart:</span>
        <button
          onClick={() => setQualityFilter(null)}
          className={clsx('px-2 py-0.5 rounded-full text-xs border transition-colors',
            !qualityFilter ? 'bg-gray-600 text-white border-gray-500' : 'text-gray-400 border-gray-700 hover:border-gray-500')}
        >Tous</button>
        {ALL_QUALITIES.map(q => (
          <button key={q} onClick={() => setQualityFilter(qualityFilter === q ? null : q)}
            className={clsx('px-2 py-0.5 rounded-full text-xs border transition-colors',
              qualityFilter === q ? QUALITY_STYLES[q] + ' font-bold' : 'text-gray-400 border-gray-700 hover:border-gray-500')}>
            {QUALITY_ICONS[q]} {q} <span className="opacity-60">({teams.filter(t => t.kart_quality === q).length})</span>
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-600">{display.length} équipes</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-900 text-gray-400 text-xs uppercase">
              <th className="px-3 py-2 text-left">Équipe</th>
              <SortTh label="Niveau"   sk="level"  cur={sortKey} dir={sortDir} onClick={onSort} />
              <SortTh label="Kart"     sk="kart"   cur={sortKey} dir={sortDir} onClick={onSort} />
              <SortTh label="Δ champ"  sk="delta"  cur={sortKey} dir={sortDir} onClick={onSort} />
              <SortTh label="Laps stint" sk="laps" cur={sortKey} dir={sortDir} onClick={onSort} />
              <SortTh label="Stints"   sk="stints" cur={sortKey} dir={sortDir} onClick={onSort} />
              <th className="px-3 py-2 text-center">Pilotes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {display.map(team => (
              <>
                <tr
                  key={team.team_id}
                  className="hover:bg-gray-800/50 cursor-pointer"
                  onClick={() => toggleExpand(team.team_id)}
                >
                  <td className="px-3 py-2 font-medium text-white">
                    <span className="mr-1 text-gray-600">{expanded === team.team_id ? '▼' : '▶'}</span>
                    {team.team_name || team.team_id}
                  </td>
                  <td className="px-3 py-2 text-center"><LevelBadge level={team.team_level} /></td>
                  <td className="px-3 py-2 text-center"><QualityBadge quality={team.kart_quality} score={team.kart_score_pct} /></td>
                  <td className="px-3 py-2 text-center font-mono text-xs">{fmtDelta(team.current_delta_pct)}</td>
                  <td className="px-3 py-2 text-center text-gray-300">{team.current_stint_laps}</td>
                  <td className="px-3 py-2 text-center text-gray-300">{team.completed_stints}</td>
                  <td className="px-3 py-2 text-center text-gray-500">
                    {team.drivers.length > 0 ? <span className="text-blue-400">{team.drivers.length}</span> : '—'}
                  </td>
                </tr>
                {expanded === team.team_id && (
                  <tr key={`${team.team_id}-stints`} className="bg-gray-900/30">
                    <td colSpan={7} className="p-0">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-gray-600 border-b border-gray-800/40">
                            <th className="pl-8 pr-2 py-1 text-left">#</th>
                            <th className="px-2 py-1 text-center">Début</th>
                            <th className="px-2 py-1 text-left">Pilote</th>
                            <th className="px-2 py-1 text-center">Niveau</th>
                            <th className="px-2 py-1 text-center">Kart</th>
                            <th className="px-2 py-1 text-center">Tours</th>
                            <th className="px-2 py-1 text-center">Moy.</th>
                            <th className="px-2 py-1 text-center">Meilleur</th>
                            <th className="px-2 py-1 text-center">Régularité</th>
                            <th className="px-2 py-1 text-center">Δ</th>
                          </tr>
                        </thead>
                        <tbody>
                          <StintRows stints={[
                            ...(dbStints[team.team_id] ?? []),
                            ...team.stints.filter(s => s.is_current),
                          ]} />
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Pilots tab ────────────────────────────────────────────────────────────────

interface PilotEntry {
  driver: DriverPerformance
  team_name: string
  stints: StintDetail[]
}

function PilotsTab({ teams, search, initialExpanded }: { teams: TeamPerformance[]; search: string; initialExpanded?: string }) {
  const [expanded, setExpanded] = useState<string | null>(initialExpanded ?? null)
  const [sortKey, setSortKey] = useState<'level' | 'laps' | 'delta' | 'stints'>('level')
  const [sortDir, setSortDir] = useState<1 | -1>(1)

  const onSort = (k: typeof sortKey) => {
    if (k === sortKey) setSortDir(d => d === 1 ? -1 : 1)
    else { setSortKey(k); setSortDir(1) }
  }

  const pilots: PilotEntry[] = useMemo(() => {
    const map = new Map<string, PilotEntry>()
    for (const team of teams) {
      for (const drv of team.drivers) {
        if (!drv.name || drv.name.startsWith('relay_')) continue
        const drvStints = team.stints.filter(s => s.driver === drv.name)
        const existing = map.get(drv.name)
        if (!existing || drvStints.length > existing.stints.length) {
          map.set(drv.name, {
            driver: drv,
            team_name: team.team_name || team.team_id,
            stints: drvStints,
          })
        }
      }
    }
    let list = [...map.values()]
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(p => p.driver.name.toLowerCase().includes(q) || p.team_name.toLowerCase().includes(q))
    }
    return list.sort((a, b) => {
      let v = 0
      if (sortKey === 'level')  v = (LEVEL_ORDER[a.driver.level] ?? 4) - (LEVEL_ORDER[b.driver.level] ?? 4)
      if (sortKey === 'laps')   v = b.driver.total_laps - a.driver.total_laps
      if (sortKey === 'delta')  v = ((a.driver.avg_delta_pct ?? 99) - (b.driver.avg_delta_pct ?? 99))
      if (sortKey === 'stints') v = b.driver.stint_count - a.driver.stint_count
      return v * sortDir
    })
  }, [teams, search, sortKey, sortDir])

  function SortThP({ label, sk }: { label: string; sk: typeof sortKey }) {
    const active = sk === sortKey
    return (
      <th className="px-3 py-2 text-center cursor-pointer select-none hover:text-white" onClick={() => onSort(sk)}>
        {label}{active ? (sortDir === 1 ? ' ↑' : ' ↓') : ''}
      </th>
    )
  }

  if (!pilots.length) return (
    <div className="text-center text-gray-600 py-10 text-sm">
      Aucun pilote identifié — les noms de pilotes doivent être transmis par Apex Timing.
    </div>
  )

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-900 text-gray-400 text-xs uppercase">
            <th className="px-3 py-2 text-left">Pilote</th>
            <th className="px-3 py-2 text-left">Équipe</th>
            <SortThP label="Niveau" sk="level" />
            <SortThP label="Tours"  sk="laps" />
            <SortThP label="Δ moy." sk="delta" />
            <SortThP label="Stints" sk="stints" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {pilots.map(({ driver: drv, team_name, stints }) => (
            <>
              <tr
                key={drv.name}
                className="hover:bg-gray-800/50 cursor-pointer"
                onClick={() => setExpanded(expanded === drv.name ? null : drv.name)}
              >
                <td className="px-3 py-2 font-medium text-blue-300">
                  <span className="mr-1 text-gray-600">{expanded === drv.name ? '▼' : '▶'}</span>
                  🪖 {drv.name}
                </td>
                <td className="px-3 py-2 text-gray-400 text-xs">{team_name}</td>
                <td className="px-3 py-2 text-center"><LevelBadge level={drv.level} /></td>
                <td className="px-3 py-2 text-center text-gray-300">{drv.total_laps}</td>
                <td className="px-3 py-2 text-center font-mono text-xs">{fmtDelta(drv.avg_delta_pct)}</td>
                <td className="px-3 py-2 text-center text-gray-400">{drv.stint_count || '—'}</td>
              </tr>
              {expanded === drv.name && stints.length > 0 && (
                <tr key={`${drv.name}-stints`} className="bg-gray-900/30">
                  <td colSpan={6} className="p-0">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-600 border-b border-gray-800/40">
                          <th className="pl-8 pr-3 py-1 text-left">#</th>
                          <th className="px-3 py-1 text-center">Tours</th>
                          <th className="px-3 py-1 text-center">Moy.</th>
                          <th className="px-3 py-1 text-center">Meilleur</th>
                          <th className="px-3 py-1 text-center">Régularité</th>
                          <th className="px-3 py-1 text-center">Δ champ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stints.map((s, i) => (
                          <tr key={i} className={clsx('border-t border-gray-800/40', s.is_current ? 'bg-blue-950/20' : 'bg-gray-900/40')}>
                            <td className="pl-8 pr-3 py-1.5 text-gray-600">
                              {s.is_current ? <span className="text-blue-400">▶</span> : `#${i + 1}`}
                            </td>
                            <td className="px-3 py-1.5 text-center text-gray-400">{s.total_laps_ms}</td>
                            <td className="px-3 py-1.5 text-center font-mono text-gray-300">{fmtMs(s.avg_ms)}</td>
                            <td className="px-3 py-1.5 text-center font-mono text-green-400">{fmtMs(s.best_ms)}</td>
                            <td className="px-3 py-1.5 text-center font-mono text-gray-400">{fmtCV(s.std_ms, s.avg_ms)}</td>
                            <td className="px-3 py-1.5 text-center font-mono">{fmtDelta(s.delta_pct)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </td>
                </tr>
              )}
              {expanded === drv.name && stints.length === 0 && (
                <tr key={`${drv.name}-empty`} className="bg-gray-900/30">
                  <td colSpan={6} className="pl-8 py-2 text-xs text-gray-600 italic">Aucun stint enregistré</td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function KartPerformancePage() {
  const [teams, setTeams] = useState<TeamPerformance[]>([])
  const [loading, setLoading] = useState(true)
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { viewedEventId } = useEventView()

  const initPilot = searchParams.get('pilot') ?? ''
  const initTeam  = searchParams.get('team')  ?? ''
  const initTab   = initPilot ? 'pilots' : 'teams'

  const [tab, setTab] = useState<'teams' | 'pilots'>(initTab as 'teams' | 'pilots')
  const [search, setSearch] = useState(initPilot || initTeam)

  useEffect(() => {
    const load = () => {
      api.performance()
        .then((r: { teams: TeamPerformance[] }) => {
          setTeams(r.teams ?? [])
          setLoading(false)
        })
        .catch(() => setLoading(false))
    }
    load()
    const t = setInterval(load, 15_000)
    return () => clearInterval(t)
  }, [])

  const pilotCount = new Set(teams.flatMap(t => t.drivers.map(d => d.name).filter(Boolean))).size

  if (viewedEventId) return <HistoricalStandings />

  if (loading) return <div className="text-gray-500 py-20 text-center">Chargement...</div>

  if (!teams.length) {
    return (
      <div className="text-gray-500 py-20 text-center">
        Aucune donnée disponible.<br />
        <span className="text-sm text-gray-600 mt-1 block">Les données apparaissent après quelques tours de piste.</span>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary chips */}
      <div className="flex flex-wrap gap-2">
        {(['ELITE', 'FAST', 'MEDIUM', 'SLOW'] as TeamLevel[]).map(l => (
          <div key={l} className={clsx('rounded-lg border px-3 py-1.5 text-center min-w-[60px]', LEVEL_STYLES[l])}>
            <div className="text-lg font-bold">{teams.filter(t => t.team_level === l).length}</div>
            <div className="text-xs">{LEVEL_ICONS[l]} {l}</div>
          </div>
        ))}
        <div className="w-px bg-gray-700 mx-1 self-stretch" />
        {(['ROCKET', 'FAST', 'MEDIUM', 'BAD'] as KartQuality[]).map(q => (
          <div key={q} className={clsx('rounded-lg border px-3 py-1.5 text-center min-w-[60px]', QUALITY_STYLES[q])}>
            <div className="text-lg font-bold">{teams.filter(t => t.kart_quality === q).length}</div>
            <div className="text-xs">{QUALITY_ICONS[q]} {q}</div>
          </div>
        ))}
      </div>

      {/* Tab bar + search */}
      <div className="flex items-center gap-3 border-b border-gray-800 pb-0">
        <div className="flex gap-1">
          {(['teams', 'pilots'] as const).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setSearch('') }}
              className={clsx(
                'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
                tab === t
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              )}
            >
              {t === 'teams' ? `Équipes (${teams.length})` : `Pilotes (${pilotCount})`}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 pb-1">
          <Search size={14} className="text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={tab === 'teams' ? 'Filtrer équipe…' : 'Filtrer pilote / équipe…'}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white placeholder-gray-600 w-52 focus:outline-none focus:border-gray-500"
          />
          {search && (
            <button onClick={() => { setSearch(''); navigate('/performance', { replace: true }) }}
              className="text-gray-500 hover:text-white text-xs">✕</button>
          )}
        </div>
      </div>

      {tab === 'teams'  && <TeamsTab  teams={teams} search={search} initialExpanded={initTeam ? teams.find(t => (t.team_name || t.team_id) === initTeam)?.team_id : undefined} />}
      {tab === 'pilots' && <PilotsTab teams={teams} search={search} initialExpanded={initPilot || undefined} />}

      <p className="text-xs text-gray-600 text-center">
        Niveau = quartile vs plateau · Δ = médiane normalisée vs champ · Régularité = CV% (std/moy) · Actualisé toutes les 15 s
      </p>
    </div>
  )
}
