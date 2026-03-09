import { useEffect, useState } from 'react'
import { getTeamMetrics } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { downloadCsv } from '../utils/export'

interface TeamDORA {
  team: string
  display: string
  dora_level: string
  deployment_frequency?: number
  lead_time?: number
  change_failure_rate?: number
  time_to_restore?: number
}

// API returns a flat shape — normalize it to TeamDORA
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalize(raw: any): TeamDORA {
  return {
    team: raw.team ?? raw.name ?? '',
    display: raw.display ?? raw.name ?? '',
    dora_level: raw.dora_level
      ? String(raw.dora_level).charAt(0).toUpperCase() + String(raw.dora_level).slice(1)
      : raw.level
      ? String(raw.level).charAt(0).toUpperCase() + String(raw.level).slice(1)
      : 'Low',
    deployment_frequency: raw.deployment_frequency?.value ?? raw.deployFreq,
    lead_time: raw.lead_time?.value ?? raw.leadTime,
    change_failure_rate: raw.change_failure_rate?.value ?? raw.failureRate,
    time_to_restore: raw.time_to_restore?.value ?? raw.restoreTime,
  }
}

const doraLevelColors: Record<string, { badge: string; border: string }> = {
  Elite: { badge: 'bg-green-500/20 text-green-400 border border-green-500/30', border: 'border-green-500/20' },
  High: { badge: 'bg-blue-500/20 text-blue-400 border border-blue-500/30', border: 'border-blue-500/20' },
  Medium: { badge: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30', border: 'border-yellow-500/20' },
  Low: { badge: 'bg-red-500/20 text-red-400 border border-red-500/30', border: 'border-red-500/20' },
}

function MetricCard({
  label,
  value,
  unit,
  emptyLabel = '-',
}: {
  label: string
  value?: number
  unit?: string
  emptyLabel?: string
}) {
  return (
    <div className="bg-gray-800/50 rounded-lg p-3">
      <p className="text-gray-400 text-xs mb-1">{label}</p>
      <p className="text-white font-bold text-lg">
        {value != null ? value.toFixed(value < 10 ? 1 : 0) : emptyLabel}
        {unit && value != null && <span className="text-gray-400 text-xs font-normal ml-1">{unit}</span>}
      </p>
    </div>
  )
}

const PERIODS = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
]

export default function DoraPage() {
  const [teams, setTeams] = useState<TeamDORA[]>([])
  const [metricsLoading, setMetricsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(30)

  useEffect(() => {
    setMetricsLoading(true)
    setError(null)
    getTeamMetrics(days)
      .then(res => {
        const data = res.data
        const raw: unknown[] = Array.isArray(data)
          ? data
          : (data as { teams?: unknown[] }).teams ?? []
        setTeams(raw.map(normalize))
      })
      .catch(err => setError(err?.message ?? 'Failed to load DORA metrics'))
      .finally(() => setMetricsLoading(false))
  }, [days])

  if (metricsLoading) return <LoadingSpinner text="Loading DORA metrics..." />

  const handleExport = () => {
    downloadCsv(`dora-${days}d.csv`, teams.map(team => ({
      team: team.display,
      slug: team.team,
      dora_level: team.dora_level,
      deployment_frequency_per_week: team.deployment_frequency ?? '',
      lead_time_hours: team.lead_time ?? '',
      change_failure_rate_pct: team.change_failure_rate ?? '',
      time_to_restore_hours: team.time_to_restore ?? '',
    })))
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">DORA Metrics</h2>
          <p className="text-gray-400 text-sm mt-1">Deployment performance by team</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleExport}
            disabled={teams.length === 0}
            className="px-3 py-2 rounded-lg border border-gray-700 text-gray-300 hover:text-white hover:border-gray-500 disabled:opacity-40 text-sm transition-colors"
          >
            Export CSV
          </button>
          <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-lg p-1">
            {PERIODS.map(p => (
              <button
                key={p.days}
                onClick={() => {
                  setDays(p.days)
                }}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  days === p.days
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {teams.length === 0 && !error ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-400">
          <p className="text-sm">No DORA data available. Configure teams and a code platform to see metrics.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {teams.map(team => {
            const colors = doraLevelColors[team.dora_level] ?? doraLevelColors['Low']
            return (
              <div
                key={team.team}
                className={`bg-gray-900 border rounded-xl p-4 space-y-3 ${colors.border}`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-white font-semibold">{team.display}</h3>
                    <p className="text-gray-500 text-xs mt-0.5">{team.team}</p>
                  </div>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors.badge}`}>
                    {team.dora_level}
                  </span>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <MetricCard label="Deploy Frequency" value={team.deployment_frequency} unit="/week" />
                  <MetricCard label="Lead Time" value={team.lead_time} unit="hrs" />
                  <MetricCard label="Change Failure Rate" value={team.change_failure_rate} unit="%" emptyLabel="Unavailable" />
                  <MetricCard label="Time to Restore" value={team.time_to_restore} unit="hrs" emptyLabel="Unavailable" />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
