import clsx from 'clsx'
import type { Driver } from '../types'
import type { LiveState } from '../hooks/useWebSocket'
import { RatingBadge } from '../components/RatingBadge'

interface Props { live: LiveState }

function fmtMs(ms: string | number): string {
  const n = typeof ms === 'string' ? parseFloat(ms.replace(',', '.')) : ms
  if (!n || n <= 0) return '-'
  if (typeof ms === 'string' && ms.includes(':')) return ms  // already formatted
  const total = n / 1000
  const m = Math.floor(total / 60)
  const s = (total % 60).toFixed(3)
  return m > 0 ? `${m}:${s.padStart(6, '0')}` : s
}

function LapCell({ value, cls }: { value: string; cls?: string }) {
  const color =
    cls === 'best' || cls === 'sb'
      ? 'text-purple-400 font-semibold'
      : cls === 'pb' || cls === 'improved'
      ? 'text-green-400'
      : 'text-gray-300'
  return <td className={clsx('px-2 py-1.5 font-mono text-xs text-right', color)}>{value || '-'}</td>
}

function PosCell({ pos, pits }: { pos: number; pits: number }) {
  return (
    <td className="px-2 py-1.5 text-center">
      <span className={clsx(
        'inline-block w-7 h-7 rounded-full text-sm font-bold leading-7 text-center',
        pits > 0 ? 'bg-orange-600' : pos === 1 ? 'bg-yellow-500 text-black' : 'bg-gray-700'
      )}>
        {pos}
      </span>
    </td>
  )
}

export function LiveTiming({ live }: Props) {
  const { drivers } = live

  if (!drivers.length) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        {live.connected ? 'En attente des données...' : 'Non connecté à Apex Timing'}
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
            <th className="px-2 py-2 text-center w-10">Pos</th>
            <th className="px-2 py-2 text-left">Équipe</th>
            <th className="px-2 py-2 text-center">Kart</th>
            <th className="px-2 py-2 text-right">Gap</th>
            <th className="px-2 py-2 text-right">Int.</th>
            <th className="px-2 py-2 text-right">S1</th>
            <th className="px-2 py-2 text-right">S2</th>
            <th className="px-2 py-2 text-right">S3</th>
            <th className="px-2 py-2 text-right">Dernier</th>
            <th className="px-2 py-2 text-right">Meilleur</th>
            <th className="px-2 py-2 text-center">Tours</th>
            <th className="px-2 py-2 text-center">Stands</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {drivers.map((d: Driver, idx) => (
            <tr
              key={d.driver_id}
              className={clsx(
                'transition-colors',
                d.pits > 0 ? 'bg-orange-950/30' : idx % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50',
                'hover:bg-gray-800/50'
              )}
            >
              <PosCell pos={d.position} pits={d.pits} />
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-white">{d.team || '-'}</span>
                  {d.kart_rating && <RatingBadge rating={d.kart_rating} showDelta />}
                </div>
                {d.kart_label && d.kart_label !== '?' && (
                  <div className="text-xs text-gray-500 mt-0.5">Kart: {d.kart_label}</div>
                )}
              </td>
              <td className="px-2 py-1.5 text-center">
                <span className="bg-gray-700 text-white text-xs font-mono px-2 py-0.5 rounded">
                  #{d.kart}
                </span>
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-300">{d.gap || '-'}</td>
              <td className="px-2 py-1.5 text-right font-mono text-xs text-gray-400">{d.interval || '-'}</td>
              <LapCell value={d.s1} />
              <LapCell value={d.s2} />
              <LapCell value={d.s3} />
              <LapCell value={d.last_lap} cls={d.last_lap_class} />
              <LapCell value={d.best_lap} cls="best" />
              <td className="px-2 py-1.5 text-center text-gray-300">{d.laps || 0}</td>
              <td className="px-2 py-1.5 text-center">
                {d.pits > 0 ? (
                  <span className="bg-orange-600 text-white text-xs px-2 py-0.5 rounded-full font-bold">
                    {d.pits}
                  </span>
                ) : (
                  <span className="text-gray-600">0</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
