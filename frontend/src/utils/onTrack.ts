/** Parse Apex "M:SS" or "MM:SS" string to total seconds. Returns null if unparseable. */
export function parseOnTrack(s: string | null | undefined): number | null {
  if (!s) return null
  const m = s.match(/^(\d+):(\d{2})$/)
  if (!m) return null
  return parseInt(m[1]) * 60 + parseInt(m[2])
}

export function onTrackCls(
  raw: string | null | undefined,
  inPit: boolean,
  maxRelayS: number,
  isFav: boolean,
): { cell: string; pulse: boolean } {
  const s = parseOnTrack(raw)
  if (s === null) return { cell: 'text-gray-600', pulse: false }
  if (inPit) return { cell: 'text-blue-400', pulse: false }
  const timeToMax = maxRelayS - s
  if (timeToMax <= 300 && timeToMax >= 0 && isFav) return { cell: 'text-orange-400', pulse: true }
  return { cell: 'text-red-400', pulse: false }
}
