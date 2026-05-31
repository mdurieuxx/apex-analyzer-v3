import clsx from 'clsx'
import type { KartQuality, KartRating } from '../types'

const QUALITY_STYLES: Record<KartQuality, string> = {
  ROCKET:  'bg-purple-500/20 text-purple-300 border-purple-500/50',
  FAST:    'bg-green-500/20  text-green-400  border-green-500/50',
  MEDIUM:  'bg-orange-500/20 text-orange-400 border-orange-500/50',
  BAD:     'bg-red-500/20    text-red-400    border-red-500/50',
  UNKNOWN: 'bg-gray-700/40   text-gray-500   border-gray-600/50',
}

const ICONS: Record<KartQuality, string> = {
  ROCKET: '🚀', FAST: '🟢', MEDIUM: '🟠', BAD: '🔴', UNKNOWN: '❓',
}

interface Props {
  rating: KartRating | undefined
  size?: 'sm' | 'md'
  showDelta?: boolean
}

export function RatingBadge({ rating, size = 'sm', showDelta = false }: Props) {
  const quality: KartQuality = rating?.kart_quality ?? 'UNKNOWN'
  const conf = rating?.confidence ?? 0
  const delta = rating?.delta_pct ?? 0
  const label = quality

  // Unknown = icône seule, pas encore assez de données
  if (quality === 'UNKNOWN') {
    return (
      <span
        className={clsx(
          'inline-flex items-center justify-center border rounded-full font-bold text-gray-500 border-gray-600/50 bg-gray-700/40',
          size === 'sm' ? 'w-5 h-5 text-xs' : 'w-6 h-6 text-sm'
        )}
        title="Perf. kart inconnue — en attente de données"
      >
        ?
      </span>
    )
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 border rounded-full font-semibold whitespace-nowrap',
        QUALITY_STYLES[quality],
        size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-1 text-sm'
      )}
      title={`Kart ${label}${conf > 0 ? ` — ${conf}% confiance` : ''}${showDelta && delta !== 0 ? ` — score: ${delta > 0 ? '+' : ''}${delta}%` : ''}`}
    >
      <span>{ICONS[quality] ?? '❓'}</span>
      <span>{label}</span>
      {conf > 0 && <span className="opacity-60">{conf}%</span>}
    </span>
  )
}

export function ReserveQualityInline({ summary }: { summary: { rocket: number; fast: number; medium: number; bad: number; unknown: number } }) {
  const total = summary.rocket + summary.fast + summary.medium + summary.bad + summary.unknown
  if (total === 0 || summary.unknown === 100) return null
  return (
    <div className="flex items-center gap-1 text-xs shrink-0">
      <span className="text-gray-500 mr-0.5">Réserve:</span>
      {summary.rocket  > 0 && <span className="text-purple-400 font-semibold">🚀{summary.rocket}%</span>}
      {summary.fast    > 0 && <span className="text-green-400  font-semibold">🟢{summary.fast}%</span>}
      {summary.medium  > 0 && <span className="text-orange-400 font-semibold">🟠{summary.medium}%</span>}
      {summary.bad     > 0 && <span className="text-red-400    font-semibold">🔴{summary.bad}%</span>}
      {summary.unknown > 0 && <span className="text-gray-500">⚪{summary.unknown}%</span>}
    </div>
  )
}

export function ReserveSummaryBar({ summary }: { summary: { rocket: number; fast: number; medium: number; bad: number; unknown: number } }) {
  const total = summary.rocket + summary.fast + summary.medium + summary.bad + summary.unknown
  if (total === 0) return null

  return (
    <div className="space-y-1">
      <div className="flex h-2 rounded-full overflow-hidden gap-px">
        {summary.rocket  > 0 && <div className="bg-purple-500" style={{ width: `${summary.rocket}%` }} />}
        {summary.fast    > 0 && <div className="bg-green-500"  style={{ width: `${summary.fast}%` }} />}
        {summary.medium  > 0 && <div className="bg-orange-500" style={{ width: `${summary.medium}%` }} />}
        {summary.bad     > 0 && <div className="bg-red-500"    style={{ width: `${summary.bad}%` }} />}
        {summary.unknown > 0 && <div className="bg-gray-600"   style={{ width: `${summary.unknown}%` }} />}
      </div>
      <div className="flex gap-3 text-xs text-gray-400 flex-wrap">
        {summary.rocket  > 0 && <span className="text-purple-400">🚀 Rocket {summary.rocket}%</span>}
        {summary.fast    > 0 && <span className="text-green-400">🟢 Fast {summary.fast}%</span>}
        {summary.medium  > 0 && <span className="text-orange-400">🟠 Medium {summary.medium}%</span>}
        {summary.bad     > 0 && <span className="text-red-400">🔴 Bad {summary.bad}%</span>}
        {summary.unknown > 0 && <span className="text-gray-500">⚪ Inconnu {summary.unknown}%</span>}
      </div>
    </div>
  )
}
