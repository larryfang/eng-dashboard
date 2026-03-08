interface TrendBadgeProps {
  delta: number
  pctChange: number | null
  size?: 'sm' | 'md'
}

export default function TrendBadge({ delta, pctChange, size = 'sm' }: TrendBadgeProps) {
  if (pctChange === null) return null

  const isUp = delta > 0
  const isDown = delta < 0

  const color = isUp
    ? 'text-green-400'
    : isDown
      ? 'text-red-400'
      : 'text-gray-500'

  const arrow = isUp ? '\u2191' : isDown ? '\u2193' : '\u2192'
  const textSize = size === 'sm' ? 'text-[10px]' : 'text-xs'

  const label = `${arrow}${Math.round(Math.abs(pctChange))}%`

  return (
    <span
      className={`${color} ${textSize} font-medium whitespace-nowrap`}
      title={`${delta >= 0 ? '+' : ''}${delta} vs previous period${pctChange !== null ? ` (${pctChange >= 0 ? '+' : ''}${pctChange}%)` : ''}`}
    >
      {label}
    </span>
  )
}
