import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getEngineers, getConfig, getSectionSyncStatus, triggerSync, getSyncSchedule } from '../api/client'
import type { OrgConfig } from '../api/client'
import TrendBadge from '../components/TrendBadge'

interface EngineerWithDelta {
  username: string
  name: string
  team: string
  team_display?: string
  role?: string
  mrs_opened: number
  mrs_merged: number
  commits?: number
  reviews?: number
  last_activity?: string | null
  last_active?: string | null
  delta?: { current: number; previous: number; delta: number; pct_change: number | null }
}
import LoadingSpinner from '../components/LoadingSpinner'
import PeriodSelector, { type PeriodDays } from '../components/PeriodSelector'
import SyncStatusBadge from '../components/SyncStatusBadge'
import { formatDistanceToNow } from 'date-fns'
import { downloadCsv } from '../utils/export'

type SortKey = 'name' | 'team' | 'mrs_opened' | 'mrs_merged'

export default function Engineers() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [engineers, setEngineers] = useState<EngineerWithDelta[]>([])
  const [config, setConfig] = useState<OrgConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTeam, setSelectedTeam] = useState<string>(searchParams.get('team') ?? '')
  const [sortKey, setSortKey] = useState<SortKey>('mrs_opened')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [days, setDays] = useState<PeriodDays>(30)
  const [syncInfo, setSyncInfo] = useState<any>(null)
  const [syncing, setSyncing] = useState(false)
  const [schedulerRunning, setSchedulerRunning] = useState(false)
  const [schedulerPaused, setSchedulerPaused] = useState(false)
  const navigate = useNavigate()

  const fetchData = () => {
    setLoading(true)
    setError(null)
    Promise.all([
      getEngineers(selectedTeam || undefined, days, true),
      getConfig(),
      getSectionSyncStatus('engineers', days),
    ])
      .then(([engRes, configRes, syncRes]) => {
        setEngineers(engRes.data.engineers ?? [])
        setConfig(configRes.data)
        setSyncInfo(syncRes.data)
        // Fetch scheduler state (non-blocking)
        getSyncSchedule().then(schedRes => {
          setSchedulerRunning(schedRes.data.scheduler.running)
          setSchedulerPaused(schedRes.data.scheduler.paused)
        }).catch(() => {})
      })
      .catch(err => setError(err?.message ?? 'Failed to load engineers'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchData()
  }, [selectedTeam, days])

  const handleRefresh = async (force_full = false) => {
    setSyncing(true)
    try {
      await triggerSync('engineers', days, force_full)
      // Give the background task a moment to start, then poll
      await new Promise(r => setTimeout(r, 2000))
      fetchData()
    } finally {
      setSyncing(false)
    }
  }

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      // Default descending for numeric columns (show highest first)
      setSortDir(key === 'mrs_opened' || key === 'mrs_merged' ? 'desc' : 'asc')
    }
  }

  const sorted = [...engineers].sort((a, b) => {
    const av = a[sortKey]
    const bv = b[sortKey]
    const isNumeric = typeof av === 'number' || typeof bv === 'number'
    const da = isNumeric ? (av ?? 0) : (av ?? '')
    const db_ = isNumeric ? (bv ?? 0) : (bv ?? '')
    const cmp = da < db_ ? -1 : da > db_ ? 1 : 0
    return sortDir === 'asc' ? cmp : -cmp
  })

  const teams = config?.teams ?? []
  const handleExport = () => {
    downloadCsv(`engineers-${days}d.csv`, sorted.map(eng => ({
      username: eng.username,
      name: eng.name,
      team: eng.team,
      role: eng.role ?? '',
      mrs_opened: eng.mrs_opened,
      mrs_merged: eng.mrs_merged,
      commits: eng.commits ?? '',
      reviews: eng.reviews ?? '',
      last_activity: eng.last_activity ?? eng.last_active ?? '',
    })))
  }

  // Note: SortIcon is intentionally defined inline to access sortKey/sortDir state
  const SortIcon = ({ k }: { k: SortKey }) => {
    if (sortKey !== k) return <span className="text-gray-600 ml-1">^</span>
    return <span className="text-blue-400 ml-1">{sortDir === 'asc' ? '^' : 'v'}</span>
  }

  if (loading) return <LoadingSpinner text="Loading engineers..." />

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Engineers</h2>
          <p className="text-gray-400 text-sm mt-1">
            {engineers.length} engineer{engineers.length !== 1 ? 's' : ''} — last {days >= 365 ? '12 months' : `${days} days`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleExport}
            disabled={sorted.length === 0}
            className="px-3 py-2 rounded-lg border border-gray-700 text-gray-300 hover:text-white hover:border-gray-500 disabled:opacity-40 text-sm transition-colors"
          >
            Export CSV
          </button>
          <SyncStatusBadge syncInfo={syncInfo} onRefresh={handleRefresh} loading={syncing} schedulerRunning={schedulerRunning} schedulerPaused={schedulerPaused} />
          <PeriodSelector value={days} onChange={setDays} />
          <select
            value={selectedTeam}
            onChange={e => {
              setSelectedTeam(e.target.value)
              if (e.target.value) {
                setSearchParams({ team: e.target.value })
              } else {
                setSearchParams({})
              }
            }}
            className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
          >
            <option value="">All Teams</option>
            {teams.map(t => (
              <option key={t.key} value={t.slug ?? t.key.toLowerCase()}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400">
              <th
                className="text-left px-4 py-3 font-medium cursor-pointer hover:text-white"
                onClick={() => handleSort('name')}
              >
                Name <SortIcon k="name" />
              </th>
              <th
                className="text-left px-4 py-3 font-medium cursor-pointer hover:text-white"
                onClick={() => handleSort('team')}
              >
                Team <SortIcon k="team" />
              </th>
              <th
                className="text-right px-4 py-3 font-medium cursor-pointer hover:text-white"
                onClick={() => handleSort('mrs_opened')}
              >
                MRs Opened <SortIcon k="mrs_opened" />
              </th>
              <th
                className="text-right px-4 py-3 font-medium cursor-pointer hover:text-white"
                onClick={() => handleSort('mrs_merged')}
              >
                MRs Merged <SortIcon k="mrs_merged" />
              </th>
              <th className="text-right px-4 py-3 font-medium">Trend</th>
              <th className="text-right px-4 py-3 font-medium">Last Active</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-gray-500">
                  <p className="text-sm">No engineers found.</p>
                  <p className="text-xs text-gray-600 mt-2">
                    Add team members to <code className="text-gray-400">organization.yaml</code> and sync your code platform in{' '}
                    <a href="/settings" className="text-blue-400 hover:underline">Settings</a>.
                  </p>
                </td>
              </tr>
            ) : (
              sorted.map(eng => (
                <tr
                  key={eng.username}
                  onClick={() => navigate(`/engineers/${eng.username}?days=${days}`)}
                  className="border-b border-gray-800/50 hover:bg-gray-800/40 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3">
                    <div>
                      <p className="text-white font-medium">{eng.name || eng.username}</p>
                      <p className="text-gray-500 text-xs">@{eng.username}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-300">{eng.team}</td>
                  <td className="px-4 py-3 text-right text-gray-300">{eng.mrs_opened}</td>
                  <td className="px-4 py-3 text-right text-gray-300">{eng.mrs_merged}</td>
                  <td className="px-4 py-3 text-right">
                    {eng.delta ? (
                      <TrendBadge delta={eng.delta.delta} pctChange={eng.delta.pct_change} />
                    ) : (
                      <span className="text-gray-600 text-[10px]">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-400 text-xs">
                    {(eng.last_activity || eng.last_active)
                      ? formatDistanceToNow(new Date((eng.last_activity || eng.last_active)!), { addSuffix: true })
                      : 'Never'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
