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
 * Net time lost per pit stop (seconds) = pit_lap_ms − ref_lap_ms.
 * Uses trackRefLapMs from the backend (sliding-window median of team bests) when available,
 * falls back to median of driver best laps from the current session.
 * Returns null when insufficient data to compute a reliable estimate.
 */
export function computePitPenaltyS(
  pitHistory: Array<{ pit_lap_ms: number | null }>,
  driverBestLaps: string[],
  trackRefLapMs?: number | null,
): { penaltyS: number; refLapMs: number } | null {
  const refLapMs = trackRefLapMs ?? (() => {
    const bestMs = driverBestLaps.map(parseMs).filter(ms => ms > 0)
    return median(bestMs) || 0
  })()
  if (!refLapMs) return null

  const penalties = pitHistory
    .map(p => p.pit_lap_ms)
    .filter((ms): ms is number => ms !== null && ms > refLapMs + 30_000)
    .map(ms => (ms - refLapMs) / 1000)

  if (penalties.length < 2) return null
  return { penaltyS: median(penalties), refLapMs }
}

/** @deprecated use computePitPenaltyS */
export function estimateAvgPitS(
  pitHistory: Array<{ pit_lap_ms: number | null }>,
  driverBestLaps: string[],
): number {
  return computePitPenaltyS(pitHistory, driverBestLaps)?.penaltyS ?? 150
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
