import { useEffect, useState, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getJiraEpics, syncJira, getConfig, getEpicContributors } from '../api/client'
import type { OrgConfig, JiraEpic, EpicContributor } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { downloadCsv } from '../utils/export'
import { RefreshCw, ExternalLink, X, GitBranch, Clock, GitMerge, User } from 'lucide-react'

const priorityColors: Record<string, string> = {
  Highest: 'bg-red-500/20 text-red-400 border border-red-500/30',
  High:    'bg-orange-500/20 text-orange-400 border border-orange-500/30',
  Medium:  'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
  Low:     'bg-blue-500/20 text-blue-400 border border-blue-500/30',
  Lowest:  'bg-gray-500/20 text-gray-400 border border-gray-500/30',
}

const COLUMNS = ['To Do', 'In Progress', 'Done'] as const
type Column = typeof COLUMNS[number]

function statusToColumn(category: string | null, status: string): Column {
  const cat = (category ?? '').toLowerCase()
  const st = status.toLowerCase()
  if (cat === 'done' || st === 'done' || st === 'closed' || st === 'resolved') return 'Done'
  if (cat === 'to do' || st === 'to do' || st === 'open' || st === 'backlog') return 'To Do'
  return 'In Progress'
}

function fmtDays(days: number | null): string {
  if (days === null || days === undefined) return '—'
  if (days < 1) return `${Math.round(days * 24)}h`
  return `${days}d`
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

// ─── Contributors Modal ──────────────────────────────────────────────────────

function ContributorsModal({
  epic,
  onClose,
}: {
  epic: JiraEpic
  onClose: () => void
}) {
  const [contributors, setContributors] = useState<EpicContributor[]>([])
  const [mrCount, setMrCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    getEpicContributors(epic.key)
      .then(res => {
        setContributors(res.data.contributors)
        setMrCount(res.data.mr_count)
      })
      .catch(() => setContributors([]))
      .finally(() => setLoading(false))
  }, [epic.key])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const stateColor = (state: string) =>
    state === 'merged' ? 'text-purple-400' : state === 'opened' ? 'text-green-400' : 'text-gray-400'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col mx-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-5 border-b border-gray-800">
          <div className="space-y-1 min-w-0 pr-4">
            <div className="flex items-center gap-2">
              {epic.url ? (
                <a
                  href={epic.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-400 font-mono text-sm font-semibold hover:text-blue-300 flex items-center gap-1"
                >
                  {epic.key}
                  <ExternalLink size={11} />
                </a>
              ) : (
                <span className="text-blue-400 font-mono text-sm font-semibold">{epic.key}</span>
              )}
              {epic.priority && (
                <span className={`text-xs px-2 py-0.5 rounded-full ${priorityColors[epic.priority] ?? 'bg-gray-700 text-gray-300'}`}>
                  {epic.priority}
                </span>
              )}
              <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full border border-gray-700">
                {epic.status}
              </span>
            </div>
            <p className="text-white font-medium text-sm">{epic.summary}</p>
            {epic.assignee && (
              <p className="text-gray-500 text-xs">Assigned: {epic.assignee}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 shrink-0 mt-0.5"
            aria-label="Close modal"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 p-5 space-y-4">
          {loading ? (
            <div className="py-8">
              <LoadingSpinner text="Loading contributors..." />
            </div>
          ) : contributors.length === 0 ? (
            <div className="text-center py-10 space-y-2">
              <p className="text-gray-400 text-sm">No linked MR activity found for {epic.key}</p>
              <p className="text-gray-600 text-xs">
                MRs are linked when the epic key appears in the branch name or MR title
              </p>
            </div>
          ) : (
            <>
              <p className="text-gray-500 text-xs">
                {contributors.length} engineer{contributors.length !== 1 ? 's' : ''} · {mrCount} MR{mrCount !== 1 ? 's' : ''}
              </p>

              {contributors.map(c => (
                <div key={c.username} className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
                  {/* Engineer row */}
                  <button
                    className="w-full text-left px-4 py-3 hover:bg-gray-750 transition-colors"
                    onClick={() => setExpanded(expanded === c.username ? null : c.username)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <User size={14} className="text-gray-400 shrink-0" />
                        <div className="min-w-0">
                          <span className="text-white text-sm font-medium">{c.name}</span>
                          {c.team_display && (
                            <span className="text-gray-500 text-xs ml-2">{c.team_display}</span>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-4 shrink-0 text-xs">
                        {/* Active span: calendar days from first → last activity on this epic */}
                        <div
                          className="flex items-center gap-1 text-amber-400"
                          title={`Active span: ${fmtDays(c.calendar_days)} from first to last activity on this epic (${fmtDate(c.first_activity)} → ${fmtDate(c.last_activity)})`}
                        >
                          <Clock size={12} />
                          <span className="font-mono">{fmtDays(c.calendar_days)}</span>
                          <span className="text-amber-600 text-[10px]">span</span>
                        </div>

                        {/* Avg cycle per MR */}
                        {c.avg_cycle_days !== null && (
                          <div className="text-gray-400" title="Average MR cycle time (first commit → merge) across their MRs on this epic">
                            ~{fmtDays(c.avg_cycle_days)}/MR
                          </div>
                        )}

                        {/* MR counts */}
                        <div className="flex items-center gap-1 text-purple-400" title="Merged MRs">
                          <GitMerge size={12} />
                          <span>{c.merged_count}</span>
                        </div>
                        {c.open_count > 0 && (
                          <div className="flex items-center gap-1 text-green-400" title="Open MRs">
                            <span>+{c.open_count} open</span>
                          </div>
                        )}

                        {/* Date range */}
                        <div className="text-gray-500 hidden sm:block">
                          {fmtDate(c.first_activity)} → {fmtDate(c.last_activity)}
                        </div>

                        {/* Branch count */}
                        <div className="flex items-center gap-1 text-blue-400" title="Feature branches">
                          <GitBranch size={12} />
                          <span>{c.branches.length}</span>
                        </div>
                      </div>
                    </div>

                    {/* Branches preview */}
                    {c.branches.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {c.branches.map(b => (
                          <span
                            key={b}
                            className="text-xs font-mono bg-gray-700/60 text-blue-300 px-1.5 py-0.5 rounded truncate max-w-[200px]"
                            title={b}
                          >
                            {b}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>

                  {/* Expanded MR list */}
                  {expanded === c.username && (
                    <div className="border-t border-gray-700 divide-y divide-gray-700/50">
                      {c.mrs.map((mr, i) => (
                        <div key={i} className="px-4 py-2.5 flex items-start gap-3">
                          <span className={`text-xs font-mono mt-0.5 shrink-0 ${stateColor(mr.state)}`}>
                            {mr.state}
                          </span>
                          <div className="min-w-0 flex-1 space-y-0.5">
                            {mr.web_url ? (
                              <a
                                href={mr.web_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-white text-xs hover:text-blue-400 line-clamp-1 block"
                              >
                                {mr.title}
                              </a>
                            ) : (
                              <p className="text-white text-xs line-clamp-1">{mr.title}</p>
                            )}
                            {mr.branch && (
                              <p className="text-blue-300 text-xs font-mono truncate">{mr.branch}</p>
                            )}
                          </div>
                          <div className="text-right text-xs text-gray-500 shrink-0 space-y-0.5">
                            {mr.cycle_time_hours !== null && (
                              <div className="text-amber-400">{fmtDays(mr.cycle_time_hours / 24)}</div>
                            )}
                            <div>{fmtDate(mr.merged_at ?? mr.created_at)}</div>
                            {(mr.lines_added || mr.lines_removed) && (
                              <div>
                                <span className="text-green-500">+{mr.lines_added ?? 0}</span>
                                {' '}
                                <span className="text-red-500">-{mr.lines_removed ?? 0}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Epic Card ───────────────────────────────────────────────────────────────

function EpicCard({ epic, onClick }: { epic: JiraEpic; onClick: () => void }) {
  const pColor = priorityColors[epic.priority ?? ''] ?? 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
  const progress = epic.progress_percent ?? (
    epic.child_issues_total
      ? Math.round(((epic.child_issues_done ?? 0) / epic.child_issues_total) * 100)
      : null
  )

  return (
    <div
      className="bg-gray-800 border border-gray-700 rounded-lg p-3 space-y-2 cursor-pointer hover:border-blue-500/50 hover:bg-gray-750 transition-colors group"
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {/* Key is the Jira link */}
          {epic.url ? (
            <a
              href={epic.url}
              target="_blank"
              rel="noreferrer"
              onClick={e => e.stopPropagation()}
              className="text-blue-400 text-xs font-mono shrink-0 hover:text-blue-300 hover:underline flex items-center gap-0.5"
            >
              {epic.key}
              <ExternalLink size={9} className="opacity-50 group-hover:opacity-100" />
            </a>
          ) : (
            <span className="text-blue-400 text-xs font-mono shrink-0">{epic.key}</span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {epic.priority && (
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${pColor}`}>
              {epic.priority}
            </span>
          )}
        </div>
      </div>

      <p className="text-white text-xs leading-snug line-clamp-2">{epic.summary}</p>

      {epic.assignee && (
        <p className="text-gray-500 text-xs">{epic.assignee}</p>
      )}

      {progress !== null && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-500">
            <span>{epic.child_issues_done ?? 0}/{epic.child_issues_total ?? 0} issues</span>
            <span>{progress}%</span>
          </div>
          <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full"
              style={{ width: `${Math.min(progress, 100)}%` }}
            />
          </div>
        </div>
      )}

      <p className="text-gray-600 text-xs opacity-0 group-hover:opacity-100 transition-opacity">
        Click to see engineer contributions →
      </p>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function JiraPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [epics, setEpics] = useState<JiraEpic[]>([])
  const [config, setConfig] = useState<OrgConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [selectedTeam, setSelectedTeam] = useState(searchParams.get('team') ?? '')
  const [activeEpic, setActiveEpic] = useState<JiraEpic | null>(null)
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const epicParam = searchParams.get('epic') ?? ''

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      getJiraEpics(selectedTeam || undefined),
      getConfig(),
    ])
      .then(([epicRes, configRes]) => {
        setEpics(epicRes.data.epics ?? [])
        setConfig(configRes.data)
      })
      .finally(() => setLoading(false))
  }, [selectedTeam])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load() }, [load])

  useEffect(() => {
    const currentTeam = searchParams.get('team') ?? ''
    if (currentTeam !== selectedTeam) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedTeam(currentTeam)
    }
  }, [searchParams, selectedTeam])

  useEffect(() => {
    if (!epicParam) {
      return
    }
    const match = epics.find(epic => epic.key === epicParam)
    if (match && activeEpic?.key !== match.key) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveEpic(match)
    }
  }, [activeEpic?.key, epicParam, epics])

  useEffect(() => {
    return () => {
      if (syncTimerRef.current) clearTimeout(syncTimerRef.current)
    }
  }, [])

  const handleSync = async () => {
    setSyncing(true)
    try {
      await syncJira()
      syncTimerRef.current = setTimeout(() => { load(); setSyncing(false) }, 3000)
    } catch {
      setSyncing(false)
    }
  }

  const handleExport = () => {
    downloadCsv(`jira-epics${selectedTeam ? `-${selectedTeam}` : ''}.csv`, epics.map(epic => ({
      key: epic.key,
      project: epic.project,
      team: epic.team ?? '',
      status: epic.status,
      priority: epic.priority ?? '',
      assignee: epic.assignee ?? '',
      progress_percent: epic.progress_percent ?? '',
      child_issues_total: epic.child_issues_total ?? '',
      child_issues_done: epic.child_issues_done ?? '',
      due_date: epic.due_date ?? '',
      summary: epic.summary,
    })))
  }

  const updateParams = (team: string, epicKey?: string | null) => {
    const next = new URLSearchParams(searchParams)
    if (team) next.set('team', team)
    else next.delete('team')
    if (epicKey) next.set('epic', epicKey)
    else next.delete('epic')
    setSearchParams(next, { replace: true })
  }

  const handleTeamChange = (value: string) => {
    setSelectedTeam(value)
    setActiveEpic(null)
    updateParams(value, null)
  }

  const openEpic = (epic: JiraEpic) => {
    setActiveEpic(epic)
    updateParams(selectedTeam, epic.key)
  }

  const closeEpic = () => {
    setActiveEpic(null)
    updateParams(selectedTeam, null)
  }

  const grouped: Record<Column, JiraEpic[]> = { 'To Do': [], 'In Progress': [], 'Done': [] }
  epics.forEach(e => {
    grouped[statusToColumn(e.status_category, e.status)].push(e)
  })

  const teams = config?.teams ?? []
  const isEmpty = !loading && epics.length === 0

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Jira Epics</h2>
          <p className="text-gray-400 text-sm mt-1">
            {epics.length} epics{selectedTeam ? ` — ${selectedTeam}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            disabled={epics.length === 0}
            className="px-3 py-2 rounded-lg border border-gray-700 text-gray-300 hover:text-white hover:border-gray-500 disabled:opacity-40 text-sm transition-colors"
          >
            Export CSV
          </button>
          <select
            value={selectedTeam}
            onChange={e => handleTeamChange(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
          >
            <option value="">All Teams</option>
            {teams.map(t => (
              <option key={t.key} value={t.key}>{t.name}</option>
            ))}
          </select>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-lg transition-colors"
          >
            <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing...' : 'Sync Jira'}
          </button>
        </div>
      </div>

      {loading ? (
        <LoadingSpinner text="Loading epics..." />
      ) : isEmpty ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center space-y-3">
          <p className="text-white font-medium">No epics synced yet</p>
          <p className="text-gray-400 text-sm">
            Click "Sync Jira" to pull epics from your Jira projects.
          </p>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="mt-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-lg transition-colors inline-flex items-center gap-2"
          >
            <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing...' : 'Sync Jira now'}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {COLUMNS.map(col => (
            <div key={col} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
                <h3 className="text-white font-medium text-sm">{col}</h3>
                <span className="bg-gray-700 text-gray-300 text-xs px-2 py-0.5 rounded-full">
                  {grouped[col].length}
                </span>
              </div>
              <div className="p-3 space-y-2 max-h-[calc(100vh-220px)] overflow-y-auto">
                {grouped[col].length === 0 ? (
                  <p className="text-gray-600 text-xs text-center py-4">No epics</p>
                ) : (
                  grouped[col].map(e => (
                    <EpicCard key={e.key} epic={e} onClick={() => openEpic(e)} />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {activeEpic && (
        <ContributorsModal epic={activeEpic} onClose={closeEpic} />
      )}
    </div>
  )
}
