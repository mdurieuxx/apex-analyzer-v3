import { useMemo } from 'react'

// Tailwind classes for up to 6 distinct categories
const PALETTE = [
  'bg-blue-900/40 text-blue-300 border-blue-600/50',
  'bg-red-900/40 text-red-300 border-red-600/50',
  'bg-emerald-900/40 text-emerald-300 border-emerald-600/50',
  'bg-purple-900/40 text-purple-300 border-purple-600/50',
  'bg-amber-900/40 text-amber-300 border-amber-600/50',
  'bg-cyan-900/40 text-cyan-300 border-cyan-600/50',
]

export function useCategoryColors(drivers: { category?: string }[]): Record<string, string> {
  return useMemo(() => {
    const cats = [...new Set(drivers.map(d => d.category).filter(Boolean))] as string[]
    cats.sort()
    return Object.fromEntries(cats.map((c, i) => [c, PALETTE[i % PALETTE.length]]))
  }, [drivers])
}
