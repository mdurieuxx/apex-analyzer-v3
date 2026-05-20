export function parseMs(formatted: string): number {
  if (!formatted || formatted === '-') return 0
  const m1 = formatted.match(/^(\d+):(\d{2})[.,](\d{1,3})$/)
  if (m1) return (parseInt(m1[1]) * 60 + parseInt(m1[2])) * 1000 + parseInt(m1[3].padEnd(3, '0'))
  const m2 = formatted.match(/^(\d+)[.,](\d{1,3})$/)
  if (m2) return parseInt(m2[1]) * 1000 + parseInt(m2[2].padEnd(3, '0'))
  return 0
}

export function fmtMs(ms: number): string {
  if (!ms) return '-'
  const total = ms / 1000
  const m = Math.floor(total / 60)
  const s = (total % 60).toFixed(3)
  return m > 0 ? `${m}:${s.padStart(6, '0')}` : s
}

export function median(arr: number[]): number {
  if (!arr.length) return 0
  const sorted = [...arr].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/**
 * Estimate average pit stop duration in seconds.
 * Formula: median(pit_lap_ms - field_avg_lap_ms) for all stops with a recorded pit lap.
 * This is more accurate than wall-clock duration because it uses timing-system data
 * and works correctly during accelerated replay.
 */
export function estimateAvgPitS(
  pitHistory: Array<{ pit_lap_ms: number | null }>,
  driverBestLaps: string[],
): number {
  const bestMs = driverBestLaps.map(parseMs).filter(ms => ms > 0)
  const fieldAvgMs = median(bestMs)
  if (!fieldAvgMs) return 150

  const durations = pitHistory
    .map(p => p.pit_lap_ms)
    .filter((ms): ms is number => ms !== null && ms > fieldAvgMs + 30_000)
    .map(ms => (ms - fieldAvgMs) / 1000)

  return durations.length >= 2 ? median(durations) : 150
}

/** Parse an Apex Timing gap string to seconds. Returns null for lapped cars. */
export function parseGapSec(gap: string): number | null {
  if (!gap || gap === '-') return 0
  const s = gap.replace(/^\+/, '').trim()
  if (!s || s === '0') return 0
  if (/\d+\s*(lap|tour)/i.test(s)) return null
  const m = s.match(/^(\d+):(\d{2})[.,](\d{1,3})$/)
  if (m) return parseInt(m[1]) * 60 + parseInt(m[2]) + parseInt(m[3].padEnd(3, '0')) / 1000
  const m2 = s.match(/^(\d+)[.,](\d{1,3})$/)
  if (m2) return parseInt(m2[1]) + parseInt(m2[2].padEnd(3, '0')) / 1000
  return null
}

/** Format virtual gap (seconds) for display. */
export function fmtGapSec(s: number): string {
  if (s === 0) return '—'
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(1)
  return m > 0 ? `+${m}:${sec.padStart(4, '0')}` : `+${sec}`
}
