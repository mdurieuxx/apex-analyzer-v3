import clsx from 'clsx'

interface Props {
  category: string
  colorClass: string
}

export function CategoryBadge({ category, colorClass }: Props) {
  return (
    <span className={clsx(
      'inline-flex items-center justify-center border rounded font-bold text-xs px-1.5 py-0.5 shrink-0',
      colorClass,
    )}>
      {category}
    </span>
  )
}
