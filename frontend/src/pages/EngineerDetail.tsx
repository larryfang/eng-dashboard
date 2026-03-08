import { useEffect, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { getEngineer, syncEngineer } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { ArrowLeft, ExternalLink, RefreshCw } from 'lucide-react'
import PeriodSelector, { type PeriodDays } from '../components/PeriodSelector'
import { format, parseISO } from 'date-fns'

// Fields returned by the backend /api/gitlab/engineers/{username}
interface MRItem {
  title: string
  state: string
  opened_at?: string
  created_at?: string  // fallback alias
  merged_at?: string | null
  gitlab_url?: string
  web_url?: string      // fallback alias
  source_branch?: string
  cycle_time_hours?: number | null
  lines_added?: number | null
  lines_removed?: number | null
  files_changed?: number | null
  jira_tickets?: string[] | null
}

interface DayActivity {
  date: string
  mrs_opened: number
  mrs_merged: number
  commits?: number
}

interface EngineerData {
  username: string
  name: string
  team: string
  team_display?: string
  role?: string
  period_days?: number
  // Backend nests totals under summary
  summary?: { mrs_opened: number; mrs_merged: number }
  // Or flat (older shape)
  mrs_opened?: number
  mrs_merged?: number
  commits?: number
  reviews?: number
  last_active?: string | null
  last_activity?: string | null
  // Backend uses timeline; older shape used daily_activity
  timeline?: DayActivity[]
  daily_activity?: DayActivity[]
  // Backend uses mrs; older shape used merge_requests
  mrs?: MRItem[]
  merge_requests?: MRItem[]
}

const stateColors: Record<string, string> = {
  opened: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
  merged: 'bg-green-500/20 text-green-400 border border-green-500/30',
  closed: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
}

export default function EngineerDetail() {
  const { username } = useParams<{ username: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const parsedDays = Number(searchParams.get('days'))
  const [days, setDays] = useState<PeriodDays>(
    ([30, 60, 90, 365] as PeriodDays[]).includes(parsedDays as PeriodDays) ? parsedDays as PeriodDays : 90
  )
  const [data, setData] = useState<EngineerData | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handlePeriodChange = (d: PeriodDays) => {
    setDays(d)
    setSearchParams({ days: String(d) })
  }

  const load = (usr: string, periodDays: number) => {
    setLoading(true)
    setError(null)
    getEngineer(usr, periodDays)
      .then(res => setData(res.data as EngineerData))
      .catch(err => setError(err?.message ?? 'Failed to load engineer'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!username) return
    setData(null)
    load(username, days)
  }, [username, days])

  const handleSync = () => {
    if (!username || syncing) return
    setError(null)
    setSyncing(true)
    syncEngineer(username, days)
      .then(() => load(username, days))
      .catch(err => setError(err?.message ?? 'Sync failed'))
      .finally(() => setSyncing(false))
  }

  if (loading) return <LoadingSpinner text="Loading engineer data..." />

  if (!data) {
    return (
      <div className="p-6">
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
          {error ?? 'Engineer not found'}
        </div>
      </div>
    )
  }

  // Normalize nested vs flat summary
  const mrsOpened = data.summary?.mrs_opened ?? data.mrs_opened ?? 0
  const mrsMerged = data.summary?.mrs_merged ?? data.mrs_merged ?? 0
  const commits = (data.summary as any)?.commits ?? data.commits ?? 0
  const reviews = (data.summary as any)?.reviews ?? data.reviews ?? 0
  const periodDays = data.period_days ?? 90

  // Normalize timeline field name
  const activityData = data.timeline ?? data.daily_activity ?? []
  const chartData = activityData.map(d => ({
    date: d.date,
    'MRs Opened': d.mrs_opened,
    'MRs Merged': d.mrs_merged,
    Commits: d.commits ?? 0,
  }))

  // Normalize MR list field name
  const mrList = data.mrs ?? data.merge_requests ?? []

  return (
    <div className="p-6 space-y-6">
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => window.history.length > 1 ? navigate(-1) : navigate('/engineers')}
            className="text-gray-400 hover:text-white transition-colors p-1"
            aria-label="Go back"
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <h2 className="text-xl font-bold text-white">{data.name || data.username}</h2>
            <p className="text-gray-400 text-sm">
              @{data.username} &middot; {data.team_display ?? data.team}{data.role ? ` · ${data.role}` : ''} &middot; last {periodDays >= 365 ? '12 months' : `${periodDays} days`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <PeriodSelector value={days} onChange={handlePeriodChange} />
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-800 border border-gray-700 text-gray-300 hover:text-white hover:border-gray-500 disabled:opacity-40 transition-colors"
          >
            <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing…' : 'Sync from GitLab'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'MRs Opened', value: mrsOpened },
          { label: 'MRs Merged', value: mrsMerged },
          { label: 'Commits', value: commits },
          { label: 'Reviews', value: reviews },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-gray-400 text-xs mb-1">{label}</p>
            <p className="text-white text-2xl font-bold">{value}</p>
          </div>
        ))}
      </div>

      {chartData.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h3 className="text-white font-semibold text-sm mb-4">Activity (last {periodDays >= 365 ? '12 months' : `${periodDays} days`})</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#9CA3AF', fontSize: 10 }}
                tickFormatter={d => {
                  try { return format(parseISO(d), 'MMM d') } catch { return d }
                }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fill: '#9CA3AF', fontSize: 10 }} allowDecimals={false} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151', borderRadius: '8px' }}
                labelStyle={{ color: '#F9FAFB' }}
                itemStyle={{ color: '#D1D5DB' }}
              />
              <Bar dataKey="MRs Opened" fill="#3B82F6" radius={[2, 2, 0, 0]} />
              <Bar dataKey="MRs Merged" fill="#10B981" radius={[2, 2, 0, 0]} />
              <Bar dataKey="Commits" fill="#8B5CF6" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {mrList.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800">
            <h3 className="text-white font-semibold text-sm">Merge Requests ({mrList.length})</h3>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-400">
                <th className="text-left px-4 py-2 font-medium">Title</th>
                <th className="text-left px-4 py-2 font-medium">Status</th>
                <th className="text-left px-4 py-2 font-medium">Opened</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {mrList.map((mr, i) => {
                const openedDate = mr.opened_at ?? mr.created_at
                const linkUrl = mr.gitlab_url ?? mr.web_url
                return (
                  <tr key={mr.gitlab_url ?? mr.web_url ?? `mr-${i}`} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-4 py-2 text-gray-200 max-w-xs truncate">{mr.title}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${stateColors[mr.state] ?? ''}`}>
                        {mr.state}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-400 text-xs">
                      {openedDate
                        ? format(parseISO(openedDate), 'MMM d, yyyy')
                        : '-'}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {linkUrl && (
                        <a
                          href={linkUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-gray-500 hover:text-blue-400 transition-colors"
                          onClick={e => e.stopPropagation()}
                        >
                          <ExternalLink size={14} />
                        </a>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
