export type PeriodDays = 30 | 60 | 90 | 365

interface Props {
  value: PeriodDays
  onChange: (days: PeriodDays) => void
}

const LABELS: Record<PeriodDays, string> = {
  30: '30d',
  60: '60d',
  90: '90d',
  365: '12m',
}

export default function PeriodSelector({ value, onChange }: Props) {
  return (
    <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-lg p-0.5">
      {([30, 60, 90, 365] as const).map(d => (
        <button
          key={d}
          onClick={() => onChange(d)}
          className={`px-3 py-1 text-xs rounded-md transition-colors ${
            value === d
              ? 'bg-blue-600 text-white'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          {LABELS[d]}
        </button>
      ))}
    </div>
  )
}
