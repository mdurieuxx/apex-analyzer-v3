import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Flag, Users, ChevronLeft, ChevronDown, ChevronRight, Trophy } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import { fmtMs } from '../utils/lapTime'
import type { PilotProfile, TeamProfile, StintStat } from '../types'
import { median, speedStars, consistencyStars, RatingCell, fmtCV } from '../utils/statsHelpers'

// ── Shared stint display ──────────────────────────────────────────────────

const KART_Q_COLORS: Record<string, string> = {
  ROCKET: 'text-purple-400', FAST: 'text-green-400', MEDIUM: 'text-gray-400',
  BAD: 'text-red-400', UNKNOWN: 'text-gray-600',
}
const KART_Q_LABELS: Record<string, string> = {
  ROCKET: '🚀', FAST: 'Bon', MEDIUM: '—', BAD: 'Mauvais', UNKNOWN: '—',
}
const LEVEL_COLORS: Record<string, string> = {
  ELITE: 'text-purple-400', FAST: 'text-blue-400',
  MEDIUM: 'text-yellow-400', SLOW: 'text-red-400', UNKNOWN: 'text-gray-600',
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function fmtDur(ms: number | null): string {
  if (!ms || ms <= 0) return '—'
  const s = Math.round(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`
}

function stintDurMs(s: StintStat): number | null {
  if (s.started_at && s.ended_at)
    return new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()
  if (s.lap_count && s.avg_lap_ms) return s.lap_count * s.avg_lap_ms
  return null
}

const STINT_COLS = 'grid-cols-[22px_44px_48px_50px_36px_60px_60px_60px]'

function StintRow({ s, idx }: { s: StintStat; idx: number }) {
  return (
    <div className={clsx('px-4 py-1.5 text-xs grid gap-2', STINT_COLS,
      idx % 2 === 0 ? 'bg-gray-800/40' : 'bg-gray-800/20')}>
      <span className="text-gray-600 text-right self-center">{s.stint_number}</span>
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

function StintHeaders() {
  return (
    <div className={clsx('px-4 py-1 grid gap-2 text-xs text-gray-600 font-medium border-b border-gray-800/40', STINT_COLS)}>
      <span className="text-right">#</span>
      <span className="text-right">Niv.</span>
      <span className="text-right">Heure</span>
      <span className="text-right">Durée</span>
      <span className="text-right">T.</span>
      <span className="text-right">Best</span>
      <span className="text-right">Moy.</span>
      <span className="text-right">Kart</span>
    </div>
  )
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ── Pilot profile page ────────────────────────────────────────────────────

export function PilotProfilePage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const decodedName = name ? decodeURIComponent(name) : ''

  const [profile, setProfile] = useState<PilotProfile | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!decodedName) return
    setLoading(true)
    api.stats.pilotProfile(decodedName).then(setProfile).catch(() => {}).finally(() => setLoading(false))
  }, [decodedName])

  const evAvgs = useMemo(
    () => profile?.events.map(e => e.avg_lap_ms).filter((v): v is number => v != null) ?? [],
    [profile]
  )
  const evMedian = useMemo(() => median(evAvgs), [evAvgs])
  const globalSpeed = speedStars(profile?.avg_lap_ms ?? null, evMedian)
  const globalCons  = consistencyStars(profile?.avg_std_dev_ms ?? null, profile?.avg_lap_ms ?? null)

  const [expanded, setExpanded] = useState<number | null>(null)
  const [stintsByEntry, setStintsByEntry] = useState<Record<number, StintStat[]>>({})

  function toggleEvent(entryId: number) {
    const next = expanded === entryId ? null : entryId
    setExpanded(next)
    if (next && !(entryId in stintsByEntry)) {
      api.stats.entry(entryId)
        .then(d => setStintsByEntry(prev => ({ ...prev, [entryId]: d.stints })))
        .catch(() => setStintsByEntry(prev => ({ ...prev, [entryId]: [] })))
    }
  }

  const ECOLS = 'grid-cols-[90px_minmax(0,1fr)_minmax(0,160px)_35px_50px_65px_65px_42px_90px_24px]'

  return (
    <div className="space-y-4 max-w-5xl">
      <button onClick={() => navigate('/stats')}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-white transition-colors">
        <ChevronLeft size={12} /> Stats
      </button>

      <div className="rounded-lg border border-orange-700/40 bg-gray-900 overflow-hidden">
        {/* Header */}
        <div className="flex flex-wrap items-start gap-6 px-6 py-5 bg-orange-500/5 border-b border-orange-700/30">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <Flag size={20} className="text-orange-400 shrink-0" />
            <div>
              <h1 className="text-xl font-bold text-white">{decodedName}</h1>
              {profile && (
                <p className="text-sm text-gray-500 mt-0.5">
                  {profile.event_count} course{profile.event_count > 1 ? 's' : ''} · {profile.total_stints} stints · {profile.total_laps} tours
                </p>
              )}
            </div>
          </div>
          {profile && (
            <div className="flex items-center gap-6 shrink-0">
              <div className="text-right">
                <div className="text-xs text-gray-500">Meilleur tour</div>
                <div className="font-mono text-yellow-300">{fmtMs(profile.best_lap_ms ?? 0)}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-gray-500">Temps moyen</div>
                <div className="font-mono text-gray-300">{fmtMs(profile.avg_lap_ms ?? 0)}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-gray-500">Régularité (σ%)</div>
                <div className="font-mono text-blue-300">{fmtCV(profile.avg_std_dev_ms, profile.avg_lap_ms)}</div>
              </div>
              <RatingCell speed={globalSpeed} consistency={globalCons} />
            </div>
          )}
        </div>

        {loading && <div className="p-6 text-sm text-gray-500 animate-pulse">Chargement…</div>}

        {!loading && profile && profile.events.length === 0 && (
          <p className="p-6 text-sm text-gray-600">Aucun événement trouvé.</p>
        )}

        {!loading && profile && profile.events.length > 0 && (
          <>
            <div className={clsx('grid gap-3 px-4 py-2 text-xs text-gray-500 font-medium bg-gray-800/60', ECOLS)}>
              <span>Date</span>
              <span>Événement</span>
              <span>Équipe · Bib</span>
              <span className="text-right">St.</span>
              <span className="text-right">Tours</span>
              <span className="text-right">Best</span>
              <span className="text-right">Moy.</span>
              <span className="text-right">σ%</span>
              <span className="text-right">Niveau</span>
              <span />
            </div>
            {profile.events.map((ev, i) => {
              const sp = speedStars(ev.avg_lap_ms, evMedian)
              const co = consistencyStars(ev.avg_std_dev_ms, ev.avg_lap_ms)
              const isOpen = expanded === ev.entry_id
              const myStints = (stintsByEntry[ev.entry_id] ?? [])
                .filter(s => !s.driver_name || s.driver_name.toLowerCase() === decodedName.toLowerCase())
              return (
                <div key={ev.event_id} className="border-t border-gray-800/60">
                  <button
                    onClick={() => toggleEvent(ev.entry_id)}
                    className={clsx('w-full grid gap-3 px-4 py-2.5 text-sm text-left transition-colors hover:bg-gray-800/50', ECOLS,
                      isOpen ? 'bg-gray-800/60' : i % 2 === 0 ? 'bg-gray-900' : 'bg-gray-900/50')}>
                    <span className="text-gray-500 text-xs self-center font-mono">{fmtDate(ev.event_date)}</span>
                    <span className="text-white font-medium truncate self-center">{ev.event_name}</span>
                    <div className="min-w-0 self-center">
                      <span className="text-gray-300 truncate">{ev.team_name}</span>
                      <span className="text-gray-600 ml-1 font-mono text-xs">#{ev.bib}</span>
                    </div>
                    <span className="text-right text-gray-400 text-xs self-center">{ev.stint_count}</span>
                    <span className="text-right font-bold text-white self-center">{ev.total_laps}</span>
                    <span className="text-right font-mono text-yellow-300 text-xs self-center">{fmtMs(ev.best_lap_ms ?? 0)}</span>
                    <span className="text-right font-mono text-gray-400 text-xs self-center">{fmtMs(ev.avg_lap_ms ?? 0)}</span>
                    <span className="text-right font-mono text-blue-300/70 text-xs self-center">{fmtCV(ev.avg_std_dev_ms, ev.avg_lap_ms)}</span>
                    <div className="self-center justify-self-end"><RatingCell speed={sp} consistency={co} /></div>
                    <span className="text-gray-500 self-center justify-self-center">
                      {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="bg-gray-900/60 border-t border-gray-800/40">
                      {!(ev.entry_id in stintsByEntry)
                        ? <p className="px-4 py-2 text-xs text-gray-500 animate-pulse">Chargement…</p>
                        : myStints.length === 0
                          ? <p className="px-4 py-2 text-xs text-gray-600 italic">Aucun stint.</p>
                          : (<>
                              <StintHeaders />
                              {myStints.map((s, idx) => <StintRow key={s.id} s={s} idx={idx} />)}
                            </>)
                      }
                    </div>
                  )}
                </div>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}

// ── Team profile page ─────────────────────────────────────────────────────

export function TeamProfilePage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const decodedName = name ? decodeURIComponent(name) : ''

  const [profile, setProfile] = useState<TeamProfile | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!decodedName) return
    setLoading(true)
    api.stats.teamProfile(decodedName).then(setProfile).catch(() => {}).finally(() => setLoading(false))
  }, [decodedName])

  const evAvgs = useMemo(
    () => profile?.events.map(e => e.avg_lap_ms).filter((v): v is number => v != null) ?? [],
    [profile]
  )
  const evMedian = useMemo(() => median(evAvgs), [evAvgs])
  const globalSpeed = speedStars(profile?.avg_lap_ms ?? null, evMedian)
  const globalCons  = consistencyStars(profile?.avg_std_dev_ms ?? null, profile?.avg_lap_ms ?? null)

  const ECOLS = 'grid-cols-[90px_minmax(0,1fr)_40px_35px_50px_35px_65px_65px_42px_105px]'

  return (
    <div className="space-y-4 max-w-5xl">
      <button onClick={() => navigate('/stats')}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-white transition-colors">
        <ChevronLeft size={12} /> Stats
      </button>

      <div className="rounded-lg border border-blue-700/40 bg-gray-900 overflow-hidden">
        {/* Header */}
        <div className="flex flex-wrap items-start gap-6 px-6 py-5 bg-blue-500/5 border-b border-blue-700/30">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <Users size={20} className="text-blue-400 shrink-0" />
            <div>
              <h1 className="text-xl font-bold text-white">{decodedName}</h1>
              {profile && (
                <p className="text-sm text-gray-500 mt-0.5">
                  {profile.event_count} course{profile.event_count > 1 ? 's' : ''} · {profile.total_stints} stints · {profile.total_laps} tours
                </p>
              )}
            </div>
          </div>
          {profile && (
            <div className="flex items-center gap-6 shrink-0">
              <div className="text-right">
                <div className="text-xs text-gray-500">Meilleur tour</div>
                <div className="font-mono text-yellow-300">{fmtMs(profile.best_lap_ms ?? 0)}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-gray-500">Temps moyen</div>
                <div className="font-mono text-gray-300">{fmtMs(profile.avg_lap_ms ?? 0)}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-gray-500">Régularité (σ%)</div>
                <div className="font-mono text-blue-300">{fmtCV(profile.avg_std_dev_ms, profile.avg_lap_ms)}</div>
              </div>
              <RatingCell speed={globalSpeed} consistency={globalCons} />
            </div>
          )}
        </div>

        {loading && <div className="p-6 text-sm text-gray-500 animate-pulse">Chargement…</div>}

        {!loading && profile && profile.events.length === 0 && (
          <p className="p-6 text-sm text-gray-600">Aucun événement trouvé.</p>
        )}

        {!loading && profile && profile.events.length > 0 && (
          <>
            <div className={clsx('grid gap-3 px-4 py-2 text-xs text-gray-500 font-medium bg-gray-800/60', ECOLS)}>
              <span>Date</span>
              <span>Événement</span>
              <span className="text-right">Bib</span>
              <span className="text-right">St.</span>
              <span className="text-right">Tours</span>
              <span className="text-right">Pits</span>
              <span className="text-right">Best</span>
              <span className="text-right">Moy.</span>
              <span className="text-right">σ%</span>
              <span className="text-right">Niveau</span>
            </div>
            {profile.events.map((ev, i) => {
              const sp = speedStars(ev.avg_lap_ms, evMedian)
              const co = consistencyStars(ev.avg_std_dev_ms, ev.avg_lap_ms)
              return (
                <button key={ev.event_id}
                  onClick={() => navigate(`/stats?event=${ev.event_id}`)}
                  className={clsx('w-full grid gap-3 px-4 py-2.5 text-sm text-left border-t border-gray-800/60 hover:bg-gray-800/50 transition-colors', ECOLS,
                    i % 2 === 0 ? 'bg-gray-900' : 'bg-gray-900/50')}>
                  <span className="text-gray-500 text-xs self-center font-mono">{fmtDate(ev.event_date)}</span>
                  <span className="text-white font-medium truncate self-center">{ev.event_name}</span>
                  <span className="text-right text-gray-400 self-center font-mono text-xs">#{ev.bib}</span>
                  <span className="text-right text-gray-400 text-xs self-center">{ev.stint_count}</span>
                  <span className="text-right font-bold text-white self-center">{ev.total_laps}</span>
                  <span className="text-right text-gray-500 text-xs self-center">{ev.pit_count}</span>
                  <span className="text-right font-mono text-yellow-300 text-xs self-center">{fmtMs(ev.best_lap_ms ?? 0)}</span>
                  <span className="text-right font-mono text-gray-400 text-xs self-center">{fmtMs(ev.avg_lap_ms ?? 0)}</span>
                  <span className="text-right font-mono text-blue-300/70 text-xs self-center">{fmtCV(ev.avg_std_dev_ms, ev.avg_lap_ms)}</span>
                  <div className="self-center justify-self-end"><RatingCell speed={sp} consistency={co} /></div>
                </button>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}

// ── Stats home with Trophy icon ───────────────────────────────────────────
export function StatsPageTitle() {
  return (
    <h1 className="text-lg font-bold text-white flex items-center gap-2">
      <Trophy size={18} className="text-orange-400" /> Statistiques
    </h1>
  )
}
