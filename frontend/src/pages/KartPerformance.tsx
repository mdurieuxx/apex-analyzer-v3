import { useState, useEffect } from 'react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { TeamPerformance, TeamLevel, KartQuality } from '../types'

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
  GOOD:    'bg-green-500/20  text-green-400  border-green-500/40',
  NEUTRAL: 'bg-gray-700/40   text-gray-400   border-gray-600/40',
  BAD:     'bg-red-500/20    text-red-400    border-red-500/40',
  UNKNOWN: 'bg-gray-800/40   text-gray-600   border-gray-700/40',
}

const QUALITY_ICONS: Record<KartQuality, string> = {
  GOOD: '🟢', NEUTRAL: '⚪', BAD: '🔴', UNKNOWN: '❓',
}

function LevelBadge({ level }: { level: TeamLevel }) {
  return (
    <span className={clsx(
      'inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-xs font-bold',
      LEVEL_STYLES[level]
    )}>
      <span>{LEVEL_ICONS[level]}</span>
      <span>{level}</span>
    </span>
  )
}

function QualityBadge({ quality, score }: { quality: KartQuality; score: number | null }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-xs font-semibold',
        QUALITY_STYLES[quality]
      )}
      title={score !== null ? `Score kart: ${score > 0 ? '+' : ''}${score.toFixed(2)}%` : ''}
    >
      <span>{QUALITY_ICONS[quality]}</span>
      <span>{quality}</span>
      {score !== null && (
        <span className="opacity-60">{score > 0 ? '+' : ''}{score.toFixed(1)}%</span>
      )}
    </span>
  )
}

const LEVELS: TeamLevel[] = ['ELITE', 'FAST', 'MEDIUM', 'SLOW']
const QUALITIES: KartQuality[] = ['GOOD', 'NEUTRAL', 'BAD']

export function KartPerformancePage() {
  const [teams, setTeams] = useState<TeamPerformance[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)

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

  if (loading) return <div className="text-gray-500 py-20 text-center">Chargement...</div>

  if (!teams.length) {
    return (
      <div className="text-gray-500 py-20 text-center">
        Aucune donnée disponible.<br />
        <span className="text-sm text-gray-600 mt-1 block">
          Les données apparaissent après quelques tours de piste.
        </span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Niveau équipes */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {LEVELS.map(level => (
          <div key={level} className={clsx('rounded-lg border px-4 py-3 text-center', LEVEL_STYLES[level])}>
            <div className="text-2xl font-bold">{teams.filter(t => t.team_level === level).length}</div>
            <div className="text-xs uppercase tracking-wide mt-1 flex items-center justify-center gap-1">
              <span>{LEVEL_ICONS[level]}</span><span>{level}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Qualité kart actuel */}
      <div className="grid grid-cols-3 gap-3">
        {QUALITIES.map(q => (
          <div key={q} className={clsx('rounded-lg border px-3 py-2 text-center', QUALITY_STYLES[q])}>
            <div className="text-xl font-bold">{teams.filter(t => t.kart_quality === q).length}</div>
            <div className="text-xs uppercase tracking-wide mt-0.5 flex items-center justify-center gap-1">
              <span>{QUALITY_ICONS[q]}</span><span>Kart {q}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Tableau équipes */}
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-900 text-gray-400 text-xs uppercase">
              <th className="px-3 py-2 text-left">Équipe</th>
              <th className="px-3 py-2 text-center">Niveau</th>
              <th className="px-3 py-2 text-center">Kart actuel</th>
              <th className="px-3 py-2 text-right">Δ champ</th>
              <th className="px-3 py-2 text-center">Tours stint</th>
              <th className="px-3 py-2 text-center">Stints</th>
              <th className="px-3 py-2 text-center">Pilotes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {teams.map(team => (
              <>
                <tr
                  key={team.team_id}
                  className="hover:bg-gray-800/50 cursor-pointer"
                  onClick={() => setExpanded(expanded === team.team_id ? null : team.team_id)}
                >
                  <td className="px-3 py-2 font-medium text-white">
                    {team.team_name || team.team_id}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <LevelBadge level={team.team_level} />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <QualityBadge quality={team.kart_quality} score={team.kart_score_pct} />
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {team.current_delta_pct !== null ? (
                      <span className={
                        team.current_delta_pct < 0 ? 'text-green-400' :
                        team.current_delta_pct > 2 ? 'text-red-400' : 'text-gray-300'
                      }>
                        {team.current_delta_pct > 0 ? '+' : ''}{team.current_delta_pct.toFixed(2)}%
                      </span>
                    ) : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-3 py-2 text-center text-gray-300">{team.current_stint_laps}</td>
                  <td className="px-3 py-2 text-center text-gray-300">{team.completed_stints}</td>
                  <td className="px-3 py-2 text-center text-gray-500">
                    {team.drivers.length > 0
                      ? <span className="text-blue-400">{team.drivers.length} ▾</span>
                      : '—'
                    }
                  </td>
                </tr>
                {expanded === team.team_id && team.drivers.length > 0 && (
                  <tr key={`${team.team_id}-drivers`} className="bg-gray-900/60">
                    <td colSpan={7} className="px-6 py-3">
                      <div className="flex flex-wrap gap-3">
                        {team.drivers.map(drv => (
                          <div key={drv.name} className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-1.5">
                            <span className="text-blue-300 text-sm">🪖 {drv.name}</span>
                            <LevelBadge level={drv.level} />
                            <span className="text-gray-500 text-xs">{drv.total_laps} tours</span>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-600 text-center">
        Niveau = quartile vs plateau. Kart = performance actuelle vs niveau attendu de l'équipe. Actualisé toutes les 15s.
      </p>
    </div>
  )
}
