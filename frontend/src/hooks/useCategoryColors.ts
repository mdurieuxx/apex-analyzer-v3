import { useMemo } from 'react'

// Tailwind classes for categories that don't carry their own color
const PALETTE = [
  'bg-blue-900/40 text-blue-300 border-blue-600/50',
  'bg-red-900/40 text-red-300 border-red-600/50',
  'bg-emerald-900/40 text-emerald-300 border-emerald-600/50',
  'bg-purple-900/40 text-purple-300 border-purple-600/50',
  'bg-amber-900/40 text-amber-300 border-amber-600/50',
  'bg-cyan-900/40 text-cyan-300 border-cyan-600/50',
]

export interface CategoryStyle {
  cls: string        // Tailwind classes (empty when inlineColor is set)
  inlineColor?: string  // decoded #RRGGBB from notc{decimal} server class
  label: string      // clean display label
}

/** Decode an Apex Timing category key to display info.
 *  notc{decimal} → server-defined RGB color + numeric label
 *  no{N}         → palette color + label N
 *  "1", "2"…     → palette color + label as-is
 */
export function useCategoryColors(drivers: { category?: string }[]): Record<string, CategoryStyle> {
  return useMemo(() => {
    const cats = [...new Set(drivers.map(d => d.category).filter(Boolean))] as string[]
    cats.sort()
    return Object.fromEntries(cats.map((c, i) => {
      // notc{decimal} — server-defined RGB (decimal integer encoding)
      const notcM = c.match(/^notc(\d+)$/)
      if (notcM) {
        const n = parseInt(notcM[1])
        const hex = '#' + n.toString(16).padStart(6, '0').toUpperCase()
        return [c, { cls: '', inlineColor: hex, label: String(i + 1) }]
      }
      // no{N} — kart CSS category (e.g. "no1", "no2")
      const noM = c.match(/^no(\d+)$/)
      const label = noM ? noM[1] : c
      return [c, { cls: PALETTE[i % PALETTE.length], label }]
    }))
  }, [drivers])
}
