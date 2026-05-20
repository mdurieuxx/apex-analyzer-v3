import { useMemo } from 'react'
import type { Driver } from '../types'
import { parseMs, median } from '../utils/lapTime'

type Condition = 'OPTIMAL' | 'CORRECT' | 'DEGRADED' | 'RAIN' | 'HEAVY_RAIN' | 'UNKNOWN'

const CONDITIONS: Record<Condition, { label: string; icon: string; cls: string }> = {
  OPTIMAL:    { label: 'Optimal',      icon: '☀️',  cls: 'bg-green-500/20 border-green-500/40 text-green-400' },
  CORRECT:    { label: 'Correct',      icon: '⛅',  cls: 'bg-yellow-500/20 border-yellow-500/40 text-yellow-300' },
  DEGRADED:   { label: 'Dégradé',     icon: '🌦️', cls: 'bg-orange-500/20 border-orange-500/40 text-orange-400' },
  RAIN:       { label: 'Pluie',        icon: '🌧️', cls: 'bg-blue-500/20 border-blue-500/40 text-blue-400' },
  HEAVY_RAIN: { label: 'Pluie forte',  icon: '⛈️', cls: 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300' },
  UNKNOWN:    { label: 'Piste',        icon: '🏁',  cls: 'bg-gray-700/40 border-gray-600/40 text-gray-400' },
}

// Thresholds (delta vs median of personal bests, in seconds)
// 0-0.5 OPTIMAL | 0.5-1 CORRECT | 1-5 DEGRADED | 5-20 RAIN | >20 HEAVY_RAIN
function classify(deltaS: number): Condition {
  if (deltaS < 0.5) return 'OPTIMAL'
  if (deltaS < 1.0) return 'CORRECT'
  if (deltaS < 5.0) return 'DEGRADED'
  if (deltaS < 20)  return 'RAIN'
  return 'HEAVY_RAIN'
}

export function TrackCondition({ drivers }: { drivers: Driver[] }) {
  const { condition, deltaMs } = useMemo(() => {
    const best = drivers.map(d => parseMs(d.best_lap)).filter(t => t > 10_000)
    const last = drivers.filter(d => !d.in_pit).map(d => parseMs(d.last_lap)).filter(t => t > 10_000)

    if (best.length < 3 || last.length < 3) return { condition: 'UNKNOWN' as Condition, deltaMs: 0 }

    const refMs = median(best)
    const curMs = median(last)
    const deltaMs = curMs - refMs
    return { condition: classify(deltaMs / 1000), deltaMs }
  }, [drivers])

  const info = CONDITIONS[condition]
  const sign = deltaMs > 0 ? '+' : ''
  const shown = Math.abs(deltaMs) > 100  // show delta only if >0.1s

  return (
    <span
      className={`inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${info.cls}`}
      title={shown ? `Conditions piste — écart médiane: ${sign}${(deltaMs / 1000).toFixed(2)}s` : 'Conditions de piste'}
    >
      <span>{info.icon}</span>
      <span>{info.label}</span>
      {shown && condition !== 'UNKNOWN' && (
        <span className="opacity-60">{sign}{(deltaMs / 1000).toFixed(1)}s</span>
      )}
    </span>
  )
}
