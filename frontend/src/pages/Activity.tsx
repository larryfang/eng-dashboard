import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { ExternalLink, GitMerge, RefreshCw } from 'lucide-react'
import { getMergeRequestActivity, type MergeRequestActivityItem, type MergeRequestActivityResponse } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { downloadCsv } from '../utils/export'

function buildRows(items: MergeRequestActivityItem[]) {
  return items.map(item => ({
    repo: item.repo_id,
    mr_iid: item.mr_iid,
    title: item.title,
    author: item.author_username,
    team: item.team ?? '',
    state: item.state,
    branch: item.source_branch ?? '',
    created_at: item.created_at ?? '',
    merged_at: item.merged_at ?? '',
    cycle_time_hours: item.cycle_time_hours ?? '',
    url: item.web_url ?? '',
  }))
}

function formatTimestamp(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('en-AU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function ActivityTable({ title, items }: { title: string; items: MergeRequestActivityItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-6 text-sm text-slate-400">
        <p>{title}: no merge requests found.</p>
        <p className="text-xs text-slate-500 mt-2">
          Ensure your code platform is connected and synced in{' '}
          <a href="/settings" className="text-blue-400 hover:underline">Settings</a>.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h3 className="text-sm font-medium text-white">{title}</h3>
        <span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
          {items.length} MRs
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/80 text-slate-400">
            <tr>
              <th className="px-4 py-3 text-left font-medium">MR</th>
              <th className="px-4 py-3 text-left font-medium">Author</th>
              <th className="px-4 py-3 text-left font-medium">State</th>
              <th className="px-4 py-3 text-left font-medium">Created</th>
              <th className="px-4 py-3 text-left font-medium">Merged</th>
              <th className="px-4 py-3 text-left font-medium">Cycle</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} className="border-t border-slate-800/70 hover:bg-slate-900/40">
                <td className="px-4 py-3 align-top">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-sky-300">!{item.mr_iid}</span>
                      {item.web_url ? (
                        <a
                          href={item.web_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-slate-300 hover:text-white"
                        >
                          Open
                          <ExternalLink size={12} />
                        </a>
                      ) : null}
                    </div>
                    <p className="text-sm text-white">{item.title}</p>
                    <p className="text-xs text-slate-500">{item.repo_id}</p>
                    {item.source_branch && <p className="text-xs font-mono text-slate-500">{item.source_branch}</p>}
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-300">
                  <div>
                    <p>{item.author_username}</p>
                    {item.team && <p className="text-xs text-slate-500">{item.team}</p>}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-300">
                    {item.state}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-300">
                  <div>
                    <p>{formatTimestamp(item.created_at)}</p>
                    {item.created_at && <p className="text-xs text-slate-500">{formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}</p>}
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-300">{formatTimestamp(item.merged_at)}</td>
                <td className="px-4 py-3 text-slate-300">
                  {item.cycle_time_hours != null ? `${item.cycle_time_hours.toFixed(1)}h` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function ActivityPage() {
  const [searchParams] = useSearchParams()
  const [data, setData] = useState<MergeRequestActivityResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const team = searchParams.get('team') ?? undefined
  const engineer = searchParams.get('engineer') ?? undefined
  const epic = searchParams.get('epic') ?? undefined
  const state = searchParams.get('state') ?? undefined
  const days = Number(searchParams.get('days') ?? '30')
  const compare = searchParams.get('compare') === '1'
  const isActiveOnly = state === 'opened' || state === 'open' || state === 'active'

  const title = useMemo(() => {
    if (isActiveOnly && engineer) return `Active merge requests for ${engineer}`
    if (isActiveOnly && epic) return `Active merge requests linked to ${epic}`
    if (isActiveOnly && team) return `Active merge requests for ${team}`
    if (engineer) return `Merge request activity for ${engineer}`
    if (epic) return `Merge requests linked to ${epic}`
    if (team) return `Merge request activity for ${team}`
    return 'Merge request activity'
  }, [engineer, epic, isActiveOnly, team])

  const load = (refresh = false) => {
    if (refresh) setRefreshing(true)
    else setLoading(true)

    getMergeRequestActivity({ team, engineer, epic, state, days, compare, limit: 120 })
      .then(res => {
        setData(res.data)
        setError(null)
      })
      .catch(err => setError(err?.message ?? 'Failed to load merge request activity'))
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }

  useEffect(() => {
    load()
  }, [team, engineer, epic, state, days, compare])

  if (loading) return <LoadingSpinner text="Loading merge requests..." />

  const current = data?.current ?? []
  const previous = data?.previous ?? []
  const flat = data?.mrs ?? []

  return (
    <div className="p-6 space-y-6">
      <div className="rounded-2xl border border-sky-500/20 bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.18),_transparent_42%),linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(2,6,23,0.96))] p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-sky-200">
              <GitMerge size={12} />
              Exact Activity
            </div>
            <div>
              <h2 className="text-2xl font-semibold text-white">{title}</h2>
              <p className="max-w-2xl text-sm leading-6 text-slate-300">
                Concrete merge requests behind the alert, anomaly, or AI evidence trail.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs text-slate-400">
              {team && <span className="rounded-full border border-slate-700 px-3 py-1">Team: {team}</span>}
              {engineer && <span className="rounded-full border border-slate-700 px-3 py-1">Engineer: {engineer}</span>}
              {epic && <span className="rounded-full border border-slate-700 px-3 py-1">Epic: {epic}</span>}
              {isActiveOnly && <span className="rounded-full border border-emerald-500/35 bg-emerald-500/10 px-3 py-1 text-emerald-200">State: active</span>}
              <span className="rounded-full border border-slate-700 px-3 py-1">Window: {days}d</span>
              {compare && <span className="rounded-full border border-slate-700 px-3 py-1">Comparing current vs previous</span>}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => downloadCsv('merge-request-activity.csv', buildRows(compare ? [...current, ...previous] : flat))}
              disabled={(compare ? current.length + previous.length : flat.length) === 0}
              className="rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:opacity-40"
            >
              Export CSV
            </button>
            <button
              onClick={() => load(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl bg-sky-400 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-300 disabled:opacity-50"
            >
              <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
              {refreshing ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {compare ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <ActivityTable title={`Current ${days}-day window`} items={current} />
          <ActivityTable title={`Previous ${days}-day window`} items={previous} />
        </div>
      ) : (
        <ActivityTable title={isActiveOnly ? 'Active merge requests' : 'Matching merge requests'} items={flat} />
      )}

      {epic && (
        <div className="text-sm text-slate-400">
          Need Jira issue context too? Open <Link to={`/jira?epic=${encodeURIComponent(epic)}`} className="text-sky-300 hover:text-sky-200">the Jira epic view</Link>.
        </div>
      )}
    </div>
  )
}
