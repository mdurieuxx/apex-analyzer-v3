import clsx from 'clsx'
import type { CategoryStyle } from '../hooks/useCategoryColors'

interface Props {
  style: CategoryStyle
}

export function CategoryBadge({ style }: Props) {
  if (style.inlineColor) {
    const c = style.inlineColor
    return (
      <span
        className="inline-flex items-center justify-center border rounded font-bold text-xs px-1.5 py-0.5 shrink-0"
        style={{
          borderColor: c + '88',
          color: c,
          backgroundColor: c + '22',
        }}
      >
        {style.label}
      </span>
    )
  }

  return (
    <span className={clsx(
      'inline-flex items-center justify-center border rounded font-bold text-xs px-1.5 py-0.5 shrink-0',
      style.cls,
    )}>
      {style.label}
    </span>
  )
}
