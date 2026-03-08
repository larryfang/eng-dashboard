import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ArrowUpRight, CalendarClock, Layers3, Search, UserRound, X } from 'lucide-react'
import type { JiraEpic } from '../api/client'
import TrendBadge from './TrendBadge'
import Sparkline from './Sparkline'

interface TeamDelta {
  current: number
  previous: number
  delta: number
  pct_change: number | null
}

interface TeamHealthCardProps {
  team: string
  display: string
  engineerCount: number
  activeMrs: number
  doraLevel: string
  warnings: string[]
  inProgressEpics?: JiraEpic[]
  days?: number
  delta?: TeamDelta | null
  sparklineData?: number[]
  onClickEngineers?: () => void
  onClickMrs?: () => void
  onClickAlerts?: () => void
  onClickEpics?: () => void
}

const doraColors: Record<string, string> = {
  Elite: 'bg-green-500/20 text-green-400 border border-green-500/30',
  High: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
  Medium: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
  Low: 'bg-red-500/20 text-red-400 border border-red-500/30',
}

const priorityColors: Record<string, string> = {
  Highest: 'border-red-500/30 bg-red-500/15 text-red-200',
  High: 'border-orange-500/30 bg-orange-500/15 text-orange-200',
  Medium: 'border-amber-500/30 bg-amber-500/15 text-amber-200',
  Low: 'border-sky-500/30 bg-sky-500/15 text-sky-200',
  Lowest: 'border-slate-500/30 bg-slate-500/15 text-slate-200',
}

function getStatusTone(statusCategory: string | null, status: string) {
  const normalizedCategory = (statusCategory ?? '').toLowerCase()
  const normalizedStatus = status.toLowerCase()
  if (normalizedCategory === 'done' || normalizedStatus === 'done') {
    return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-200'
  }
  if (normalizedCategory === 'to do' || normalizedStatus === 'open' || normalizedStatus === 'backlog') {
    return 'border-slate-500/30 bg-slate-500/15 text-slate-200'
  }
  return 'border-sky-500/30 bg-sky-500/15 text-sky-200'
}

function formatDueDate(dueDate: string | null) {
  if (!dueDate) return null
  return new Date(`${dueDate}T00:00:00`).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
  })
}

function getDueTone(dueDate: string | null) {
  if (!dueDate) return null
  const due = new Date(`${dueDate}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diffDays = Math.ceil((due.getTime() - today.getTime()) / 86400000)
  if (diffDays < 0) return 'border-red-500/30 bg-red-500/15 text-red-200'
  if (diffDays <= 3) return 'border-amber-500/30 bg-amber-500/15 text-amber-200'
  return 'border-slate-500/30 bg-slate-500/15 text-slate-200'
}

function isDueSoon(dueDate: string | null) {
  if (!dueDate) return false
  const due = new Date(`${dueDate}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diffDays = Math.ceil((due.getTime() - today.getTime()) / 86400000)
  return diffDays <= 3
}

function MetricTile({
  label,
  value,
  accent = 'text-white',
  onClick,
  children,
}: {
  label: string
  value: number
  accent?: string
  onClick?: () => void
  children?: ReactNode
}) {
  const className = `rounded-lg bg-gray-800/50 p-3 text-left transition-all ${
    onClick
      ? 'cursor-pointer border border-transparent hover:border-blue-500/30 hover:bg-slate-800/90 hover:shadow-[0_18px_40px_rgba(14,165,233,0.12)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70'
      : ''
  }`

  if (onClick) {
    return (
      <button type="button" className={className} onClick={onClick}>
        <p className="mb-1 text-xs text-gray-400">{label}</p>
        <div className="flex items-center gap-2">
          <p className={`text-lg font-bold ${accent}`}>{value}</p>
          <ArrowUpRight size={14} className="text-sky-300/80" />
        </div>
        {children}
      </button>
    )
  }

  return (
    <div className={className}>
      <p className="mb-1 text-xs text-gray-400">{label}</p>
      <p className={`text-lg font-bold ${accent}`}>{value}</p>
      {children}
    </div>
  )
}

function EpicProgressRow({
  epic,
  detailed = false,
}: {
  epic: JiraEpic
  detailed?: boolean
}) {
  const pct = epic.progress_percent ?? (
    epic.child_issues_total
      ? Math.round((epic.child_issues_done ?? 0) / epic.child_issues_total * 100)
      : null
  )
  const hasChildren = (epic.child_issues_total ?? 0) > 0
  const dueTone = getDueTone(epic.due_date)
  const formattedDue = formatDueDate(epic.due_date)

  return (
    <div className={detailed ? 'space-y-3' : 'space-y-1'}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {epic.url ? (
            <a
              href={epic.url}
              target="_blank"
              rel="noreferrer"
              className="text-blue-400 font-mono text-[10px] shrink-0 hover:text-blue-300"
              onClick={e => e.stopPropagation()}
            >
              {epic.key}
            </a>
          ) : (
            <span className="text-blue-400 font-mono text-[10px] shrink-0">{epic.key}</span>
          )}
          <span className="text-gray-300 text-[11px] truncate">{epic.summary}</span>
        </div>
        {pct !== null && (
          <span className="text-[10px] font-medium text-amber-400 shrink-0">{Math.round(pct)}%</span>
        )}
      </div>

      {detailed && (
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-[10px] font-medium ${getStatusTone(epic.status_category, epic.status)}`}>
            {epic.status}
          </span>
          {epic.priority && (
            <span className={`rounded-full border px-2.5 py-1 text-[10px] font-medium ${priorityColors[epic.priority] ?? 'border-slate-500/30 bg-slate-500/15 text-slate-200'}`}>
              {epic.priority}
            </span>
          )}
          <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] text-slate-200">
            <UserRound size={11} />
            {epic.assignee ?? 'Unassigned'}
          </span>
          {formattedDue && dueTone && (
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] ${dueTone}`}>
              <CalendarClock size={11} />
              Due {formattedDue}
            </span>
          )}
        </div>
      )}

      {hasChildren && (
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-amber-500 rounded-full transition-all"
              style={{ width: `${Math.min(pct ?? 0, 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-gray-500 shrink-0">
            {epic.child_issues_done ?? 0}/{epic.child_issues_total} done
          </span>
        </div>
      )}
    </div>
  )
}

function TeamEpicsModal({
  display,
  team,
  epics,
  onClose,
  onOpenJira,
}: {
  display: string
  team: string
  epics: JiraEpic[]
  onClose: () => void
  onOpenJira?: () => void
}) {
  const [query, setQuery] = useState('')
  const [assigneeFilter, setAssigneeFilter] = useState<'all' | 'assigned' | 'unassigned'>('all')
  const [dueSoonOnly, setDueSoonOnly] = useState(false)
  const assignedCount = useMemo(() => epics.filter(epic => Boolean(epic.assignee)).length, [epics])
  const unassignedCount = epics.length - assignedCount
  const dueSoonCount = useMemo(() => epics.filter(epic => isDueSoon(epic.due_date)).length, [epics])
  const hasActiveFilters = query.trim().length > 0 || assigneeFilter !== 'all' || dueSoonOnly
  const filteredEpics = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return epics.filter(epic => {
      if (assigneeFilter === 'assigned' && !epic.assignee) return false
      if (assigneeFilter === 'unassigned' && epic.assignee) return false
      if (dueSoonOnly && !isDueSoon(epic.due_date)) return false
      const haystack = [
        epic.key,
        epic.summary,
        epic.status,
        epic.priority ?? '',
        epic.assignee ?? '',
        epic.team ?? '',
      ].join(' ').toLowerCase()
      return normalizedQuery ? haystack.includes(normalizedQuery) : true
    })
  }, [assigneeFilter, dueSoonOnly, epics, query])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }

    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/82 p-4 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl overflow-hidden rounded-[28px] border border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.18),_transparent_36%),radial-gradient(circle_at_bottom_right,_rgba(245,158,11,0.16),_transparent_34%),linear-gradient(160deg,_rgba(15,23,42,0.98),_rgba(2,6,23,0.96))] shadow-[0_32px_90px_rgba(2,6,23,0.78)]"
        onClick={event => event.stopPropagation()}
      >
        <div className="border-b border-white/10 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/25 bg-sky-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-sky-200">
                <Layers3 size={12} />
                Full Epic List
              </div>
              <div>
                <h3 className="text-xl font-semibold text-white">{display}</h3>
                <p className="mt-1 text-sm text-slate-300">
                  {epics.length} active epic{epics.length !== 1 ? 's' : ''} currently linked to {team}.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] text-slate-200">
                  Showing {filteredEpics.length} of {epics.length}
                </span>
                <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] text-slate-200">
                  Assigned {assignedCount}
                </span>
                <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] text-slate-200">
                  Due soon {dueSoonCount}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full border border-white/10 bg-white/5 p-2 text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
              aria-label="Close epic list"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="border-b border-white/10 px-6 py-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setAssigneeFilter(current => current === 'assigned' ? 'all' : 'assigned')}
              className={`rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors ${
                assigneeFilter === 'assigned'
                  ? 'border-sky-400/40 bg-sky-400/16 text-sky-100'
                  : 'border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-white'
              }`}
            >
              Assigned · {assignedCount}
            </button>
            <button
              type="button"
              onClick={() => setAssigneeFilter(current => current === 'unassigned' ? 'all' : 'unassigned')}
              className={`rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors ${
                assigneeFilter === 'unassigned'
                  ? 'border-fuchsia-400/40 bg-fuchsia-400/16 text-fuchsia-100'
                  : 'border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-white'
              }`}
            >
              Unassigned · {unassignedCount}
            </button>
            <button
              type="button"
              onClick={() => setDueSoonOnly(current => !current)}
              className={`rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors ${
                dueSoonOnly
                  ? 'border-amber-400/40 bg-amber-400/16 text-amber-100'
                  : 'border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-white'
              }`}
            >
              Due soon · {dueSoonCount}
            </button>
            {hasActiveFilters && (
              <button
                type="button"
                onClick={() => {
                  setQuery('')
                  setAssigneeFilter('all')
                  setDueSoonOnly(false)
                }}
                className="ml-auto text-[11px] font-medium text-slate-400 transition-colors hover:text-white"
              >
                Clear all
              </button>
            )}
          </div>
          <label className="flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-950/50 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
            <Search size={15} className="shrink-0 text-slate-400" />
            <input
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder="Filter by epic, assignee, status, or priority"
              className="w-full bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
            />
          </label>
        </div>

        <div className="max-h-[68vh] space-y-4 overflow-y-auto px-6 py-5">
          {filteredEpics.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/35 px-6 py-12 text-center">
              <p className="text-sm font-medium text-white">No epics match this filter.</p>
              <p className="mt-1 text-xs text-slate-400">Try another epic key, assignee, status, priority, or clear the quick filters.</p>
              <button
                type="button"
                onClick={() => {
                  setQuery('')
                  setAssigneeFilter('all')
                  setDueSoonOnly(false)
                }}
                className="mt-4 rounded-xl border border-sky-500/25 bg-sky-500/12 px-4 py-2 text-sm text-sky-200 transition-colors hover:bg-sky-500/18"
              >
                Clear filters
              </button>
            </div>
          ) : (
            filteredEpics.map(epic => (
              <div
                key={epic.key}
                className="rounded-2xl border border-white/8 bg-slate-900/55 px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]"
              >
                <EpicProgressRow epic={epic} detailed />
              </div>
            ))
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 px-6 py-4">
          <p className="text-xs text-slate-400">
            Click an epic key to open Jira directly, or use the board shortcut for the team backlog.
          </p>
          {onOpenJira && (
            <button
              type="button"
              onClick={onOpenJira}
              className="inline-flex items-center gap-2 rounded-xl border border-sky-500/25 bg-sky-500/12 px-4 py-2 text-sm text-sky-200 transition-colors hover:bg-sky-500/18"
            >
              Open Jira Board
              <ArrowUpRight size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function TeamHealthCard({
  team,
  display,
  engineerCount,
  activeMrs,
  doraLevel,
  warnings,
  inProgressEpics = [],
  days = 30,
  delta,
  sparklineData,
  onClickEngineers,
  onClickMrs,
  onClickAlerts,
  onClickEpics,
}: TeamHealthCardProps) {
  const [showAllEpics, setShowAllEpics] = useState(false)
  const doraClass = doraColors[doraLevel] ?? doraColors['Low']
  const visibleEpics = inProgressEpics.slice(0, 5)
  const overflow = inProgressEpics.length - visibleEpics.length

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-white font-semibold text-sm">{display}</h3>
          <p className="text-gray-500 text-xs mt-0.5">{team}</p>
        </div>
        <div className="flex items-center gap-2">
          {warnings.length > 0 && (
            <span className="bg-orange-500/20 text-orange-400 border border-orange-500/30 text-xs font-medium px-2 py-0.5 rounded-full">
              {warnings.length} warning{warnings.length > 1 ? 's' : ''}
            </span>
          )}
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${doraClass}`}>
            {doraLevel}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <MetricTile
          label="Engineers"
          value={engineerCount}
          accent={onClickEngineers ? 'text-blue-400' : 'text-white'}
          onClick={onClickEngineers}
        />
        <MetricTile
          label={`Active MRs (${days}d)`}
          value={activeMrs}
          accent={onClickMrs ? 'text-blue-400' : 'text-white'}
          onClick={onClickMrs}
        >
          <div className="flex items-center gap-2">
            {delta && <TrendBadge delta={delta.delta} pctChange={delta.pct_change} />}
          </div>
          {sparklineData && sparklineData.length > 1 && (
            <div className="mt-1.5">
              <Sparkline data={sparklineData} width={100} height={20} />
            </div>
          )}
        </MetricTile>
      </div>

      {warnings.length > 0 && (
        <ul className="space-y-1">
          {warnings.map((w, i) => (
            <li key={i} className="text-xs text-orange-400 flex items-start gap-1.5">
              <span className="mt-0.5 shrink-0">!</span>
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      {visibleEpics.length > 0 && (
        <div className="border-t border-gray-800 pt-3 space-y-2.5">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide font-medium">
            In Progress · {inProgressEpics.length} epic{inProgressEpics.length !== 1 ? 's' : ''}
          </p>
          {visibleEpics.map(epic => (
            <EpicProgressRow key={epic.key} epic={epic} />
          ))}
          {overflow > 0 && (
            <button
              type="button"
              onClick={() => setShowAllEpics(true)}
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-medium text-sky-200 transition-colors hover:border-sky-400/30 hover:bg-sky-400/10"
            >
              +{overflow} more
              <ArrowUpRight size={11} />
            </button>
          )}
        </div>
      )}

      {(onClickAlerts || onClickEpics) && (
        <div className="border-t border-gray-800 pt-3 flex flex-wrap gap-2">
          {onClickAlerts && (
            <button
              onClick={onClickAlerts}
              className="text-xs px-3 py-1.5 rounded-lg bg-red-500/10 text-red-300 border border-red-500/20 hover:bg-red-500/15 transition-colors"
            >
              Open alerts
            </button>
          )}
          {onClickEpics && (
            <button
              onClick={onClickEpics}
              className="text-xs px-3 py-1.5 rounded-lg bg-blue-500/10 text-blue-300 border border-blue-500/20 hover:bg-blue-500/15 transition-colors"
            >
              Open Jira
            </button>
          )}
        </div>
      )}

      {showAllEpics && (
        <TeamEpicsModal
          display={display}
          team={team}
          epics={inProgressEpics}
          onClose={() => setShowAllEpics(false)}
          onOpenJira={onClickEpics}
        />
      )}
    </div>
  )
}
