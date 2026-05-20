export function median(values: number[]): number {
  if (!values.length) return 0
  const s = [...values].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

export function speedStars(avgMs: number | null, fieldMedian: number): number {
  if (!avgMs || avgMs <= 0 || !fieldMedian) return 0
  const d = (avgMs - fieldMedian) / fieldMedian
  if (d < -0.015) return 5
  if (d < -0.007) return 4
  if (d < 0.005)  return 3
  if (d < 0.015)  return 2
  return 1
}

export function consistencyStars(stdDev: number | null, avgMs: number | null): number {
  if (!stdDev || stdDev <= 0 || !avgMs || avgMs <= 0) return 0
  const cv = stdDev / avgMs
  if (cv < 0.0038) return 5
  if (cv < 0.0048) return 4
  if (cv < 0.0060) return 3
  if (cv < 0.0090) return 2
  return 1
}

export function globalScore(speed: number, consistency: number): number {
  if (speed === 0 && consistency === 0) return 0
  if (speed === 0) return consistency
  if (consistency === 0) return speed
  return Math.max(1, Math.min(5, Math.round(0.3 * speed + 0.7 * consistency)))
}

export function fmtCV(stdDev: number | null, avg: number | null): string {
  if (!stdDev || !avg || avg <= 0) return '—'
  return (stdDev / avg * 100).toFixed(1) + '%'
}

export function Stars({ n, max = 5, color = 'yellow' }: { n: number; max?: number; color?: 'yellow' | 'blue' }) {
  const cls = color === 'yellow' ? 'text-yellow-400' : 'text-blue-400'
  return (
    <span>
      {Array.from({ length: max }, (_, i) => (
        <span key={i} className={i < n ? cls : 'text-gray-700'}>★</span>
      ))}
    </span>
  )
}

export function RatingCell({ speed, consistency }: { speed: number; consistency: number }) {
  const g = globalScore(speed, consistency)
  if (speed === 0 && consistency === 0) return <span className="text-gray-700 text-xs">—</span>
  return (
    <div className="flex flex-col items-end gap-0.5">
      <div className="flex items-center gap-1 text-[10px]">
        <span className="text-gray-600">V</span><Stars n={speed} color="yellow" />
        <span className="text-gray-600 ml-1">R</span><Stars n={consistency} color="blue" />
      </div>
      <div className="flex items-center gap-0.5 text-xs">
        <Stars n={g} color="yellow" />
      </div>
    </div>
  )
}
