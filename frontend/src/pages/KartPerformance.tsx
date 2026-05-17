import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import clsx from 'clsx'
import { api } from '../api/client'
import type { KartPerformance } from '../types'

function fmtMs(ms: number): string {
  const total = ms / 1000
  const m = Math.floor(total / 60)
  const s = (total % 60).toFixed(3)
  return m > 0 ? `${m}:${s.padStart(6, '0')}` : s
}

const RATING_COLORS: Record<string, string> = {
  EXCELLENT: '#22c55e',
  GOOD:      '#84cc16',
  AVERAGE:   '#eab308',
  POOR:      '#ef4444',
}

const RATING_BG: Record<string, string> = {
  EXCELLENT: 'bg-green-500/20 text-green-400 border-green-500/40',
  GOOD:      'bg-lime-500/20 text-lime-400 border-lime-500/40',
  AVERAGE:   'bg-yellow-500/20 text-yellow-400 border-yellow-500/40',
  POOR:      'bg-red-500/20 text-red-400 border-red-500/40',
}

export function KartPerformancePage() {
  const [karts, setKarts] = useState<KartPerformance[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => {
      api.performance()
        .then(r => { setKarts(r.karts); setLoading(false) })
        .catch(() => setLoading(false))
    }
    load()
    const t = setInterval(load, 30_000)
    return () => clearInterval(t)
  }, [])

  if (loading) return <div className="text-gray-500 py-20 text-center">Chargement...</div>

  if (!karts.length) {
    return (
      <div className="text-gray-500 py-20 text-center">
        Aucune donnée de performance disponible.<br />
        <span className="text-sm text-gray-600 mt-1 block">
          Assignez les karts physiques aux équipes dans Paramètres pour activer le suivi.
        </span>
      </div>
    )
  }

  const chartData = karts.map(k => ({
    name: k.kart_label,
    avg_s: +(k.avg_lap_ms / 1000).toFixed(2),
    rating: k.rating,
  }))

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {(['EXCELLENT', 'GOOD', 'AVERAGE', 'POOR'] as const).map(r => {
          const count = karts.filter(k => k.rating === r).length
          return (
            <div key={r} className={clsx('rounded-lg border px-4 py-3 text-center', RATING_BG[r])}>
              <div className="text-2xl font-bold">{count}</div>
              <div className="text-xs uppercase tracking-wide mt-1">{r}</div>
            </div>
          )
        })}
      </div>

      {/* Bar chart */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <h2 className="text-sm font-semibold text-gray-400 uppercase mb-4">Temps moyen par kart (s)</h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
              labelStyle={{ color: '#fff' }}
              formatter={(v: number) => [`${v}s`, 'Moy.']}
            />
            <Bar dataKey="avg_s" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, idx) => (
                <Cell key={idx} fill={RATING_COLORS[entry.rating]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Detail table */}
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-900 text-gray-400 text-xs uppercase">
              <th className="px-3 py-2 text-left">Kart</th>
              <th className="px-3 py-2 text-center">Note</th>
              <th className="px-3 py-2 text-right">Moy. tour</th>
              <th className="px-3 py-2 text-right">Meilleur</th>
              <th className="px-3 py-2 text-right">Écart type</th>
              <th className="px-3 py-2 text-right">Score rel.</th>
              <th className="px-3 py-2 text-center">Tours</th>
              <th className="px-3 py-2 text-center">Stands</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {karts.map((k, i) => (
              <tr key={k.kart_label} className={clsx('hover:bg-gray-800/50', i === 0 && 'bg-green-950/10')}>
                <td className="px-3 py-2">
                  <span className="font-mono font-bold text-white">{k.kart_label}</span>
                  {i === 0 && <span className="ml-2 text-xs text-green-400">★ Meilleur</span>}
                </td>
                <td className="px-3 py-2 text-center">
                  <span className={clsx('text-xs font-bold border px-2 py-0.5 rounded-full', RATING_BG[k.rating])}>
                    {k.rating}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmtMs(k.avg_lap_ms)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs text-purple-400">{fmtMs(k.best_lap_ms)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs text-gray-400">±{fmtMs(k.std_dev_ms)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">
                  <span className={clsx(
                    k.relative_score <= 1.03 ? 'text-green-400' :
                    k.relative_score <= 1.07 ? 'text-lime-400' :
                    k.relative_score <= 1.12 ? 'text-yellow-400' : 'text-red-400'
                  )}>
                    {(k.relative_score * 100).toFixed(1)}%
                  </span>
                </td>
                <td className="px-3 py-2 text-center text-gray-300">{k.total_laps}</td>
                <td className="px-3 py-2 text-center text-gray-300">{k.laps_in_pit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-600 text-center">
        Score relatif = temps moyen du kart / meilleur temps en session. 100% = optimal.
        Actualisé toutes les 30s.
      </p>
    </div>
  )
}
