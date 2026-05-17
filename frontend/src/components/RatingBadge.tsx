import clsx from 'clsx'
import type { RatingLevel, KartRating } from '../types'

const STYLES: Record<RatingLevel, string> = {
  GOOD:    'bg-green-500/20  text-green-400  border-green-500/50',
  MEDIUM:  'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
  BAD:     'bg-red-500/20    text-red-400    border-red-500/50',
  UNKNOWN: 'bg-gray-700/40   text-gray-500   border-gray-600/50',
}

const ICONS: Record<RatingLevel, string> = {
  GOOD: '🟢', MEDIUM: '🟡', BAD: '🔴', UNKNOWN: '⚪',
}

interface Props {
  rating: KartRating | undefined
  size?: 'sm' | 'md'
  showDelta?: boolean
}

export function RatingBadge({ rating, size = 'sm', showDelta = false }: Props) {
  const level: RatingLevel = rating?.rating ?? 'UNKNOWN'
  const conf = rating?.confidence ?? 0
  const delta = rating?.delta_pct ?? 0

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 border rounded-full font-semibold whitespace-nowrap',
        STYLES[level],
        size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-1 text-sm'
      )}
      title={`${level} — ${conf}% confiance${showDelta ? ` — delta: ${delta > 0 ? '+' : ''}${delta}%` : ''}`}
    >
      <span>{ICONS[level]}</span>
      <span>{level}</span>
      {conf > 0 && <span className="opacity-60">{conf}%</span>}
    </span>
  )
}

export function ReserveSummaryBar({ summary }: { summary: { good: number; medium: number; bad: number; unknown: number } }) {
  const total = summary.good + summary.medium + summary.bad + summary.unknown
  if (total === 0) return null

  return (
    <div className="space-y-1">
      <div className="flex h-2 rounded-full overflow-hidden gap-px">
        {summary.good > 0    && <div className="bg-green-500"  style={{ width: `${summary.good}%` }} />}
        {summary.medium > 0  && <div className="bg-yellow-500" style={{ width: `${summary.medium}%` }} />}
        {summary.bad > 0     && <div className="bg-red-500"    style={{ width: `${summary.bad}%` }} />}
        {summary.unknown > 0 && <div className="bg-gray-600"   style={{ width: `${summary.unknown}%` }} />}
      </div>
      <div className="flex gap-3 text-xs text-gray-400 flex-wrap">
        {summary.good > 0    && <span className="text-green-400">🟢 {summary.good}%</span>}
        {summary.medium > 0  && <span className="text-yellow-400">🟡 {summary.medium}%</span>}
        {summary.bad > 0     && <span className="text-red-400">🔴 {summary.bad}%</span>}
        {summary.unknown > 0 && <span className="text-gray-500">⚪ {summary.unknown}%</span>}
      </div>
    </div>
  )
}
