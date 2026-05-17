import { useState } from 'react'
import { Star } from 'lucide-react'
import clsx from 'clsx'
import type { LiveState } from '../hooks/useWebSocket'
import { RatingBadge } from '../components/RatingBadge'
import { CategoryBadge } from '../components/CategoryBadge'
import { CategoryFilter } from '../components/CategoryFilter'
import { useFavorites } from '../hooks/useFavorites'
import { useCategoryColors } from '../hooks/useCategoryColors'

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
  const { favorites, toggle } = useFavorites()
  const catColors = useCategoryColors(drivers)
  const hasCategories = Object.keys(catColors).length > 0
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)

  const visibleDrivers = selectedCategory
    ? drivers.filter(d => d.category === selectedCategory)
    : drivers

  if (!drivers.length) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        {live.connected ? 'En attente des données...' : 'Non connecté à Apex Timing'}
      </div>
    )
  }

  return (
    <div className="space-y-3">
    {hasCategories && (
      <CategoryFilter
        categories={catColors}
        selected={selectedCategory}
        onChange={setSelectedCategory}
      />
    )}
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wide">
            <th className="px-2 py-2 w-8"></th>
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
          {visibleDrivers.map((d, idx) => {
            const isFav = favorites.has(d.driver_id)
            return (
            <tr
              key={d.driver_id}
              className={clsx(
                'transition-colors',
                isFav ? 'bg-yellow-950/20' : d.pits > 0 ? 'bg-orange-950/30' : idx % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50',
                'hover:bg-gray-800/50'
              )}
            >
              <td className="px-2 py-1.5 text-center">
                <button
                  onClick={() => toggle(d.driver_id)}
                  className={clsx('transition-colors', isFav ? 'text-yellow-400' : 'text-gray-600 hover:text-yellow-500')}
                >
                  <Star size={13} fill={isFav ? 'currentColor' : 'none'} />
                </button>
              </td>
              <PosCell pos={d.position} pits={d.pits} />
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  {hasCategories && d.category && catColors[d.category] && (
                    <CategoryBadge style={catColors[d.category]} />
                  )}
                  <span className="font-medium text-white">{d.team || '-'}</span>
                  {d.kart_rating && <RatingBadge rating={d.kart_rating} showDelta />}
                </div>
                {d.driver_name && (
                  <div className="text-xs text-blue-400 mt-0.5">🪖 {d.driver_name}</div>
                )}
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
            )
          })}
        </tbody>
      </table>
    </div>
    </div>
  )
}
