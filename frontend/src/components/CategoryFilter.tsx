import clsx from 'clsx'
import type { CategoryStyle } from '../hooks/useCategoryColors'

interface Props {
  categories: Record<string, CategoryStyle>
  selected: string | null
  onChange: (cat: string | null) => void
}

export function CategoryFilter({ categories, selected, onChange }: Props) {
  const cats = Object.entries(categories)
  if (!cats.length) return null

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <button
        onClick={() => onChange(null)}
        className={clsx(
          'text-xs px-2.5 py-1 rounded border font-medium transition-colors',
          selected === null
            ? 'bg-gray-200 text-gray-900 border-gray-200'
            : 'bg-transparent text-gray-400 border-gray-700 hover:border-gray-500'
        )}
      >
        Toutes
      </button>
      {cats.map(([key, style]) => {
        const isActive = selected === key
        if (style.inlineColor) {
          const c = style.inlineColor
          return (
            <button
              key={key}
              onClick={() => onChange(isActive ? null : key)}
              className="text-xs px-2.5 py-1 rounded border font-bold transition-opacity"
              style={{
                borderColor: c + (isActive ? 'ff' : '88'),
                color: c,
                backgroundColor: c + (isActive ? '44' : '22'),
                opacity: isActive ? 1 : 0.7,
              }}
            >
              {style.label}
            </button>
          )
        }
        return (
          <button
            key={key}
            onClick={() => onChange(isActive ? null : key)}
            className={clsx(
              'text-xs px-2.5 py-1 rounded border font-bold transition-opacity',
              style.cls,
              isActive ? 'opacity-100' : 'opacity-60 hover:opacity-80'
            )}
          >
            {style.label}
          </button>
        )
      })}
    </div>
  )
}
