import { useEffect, useMemo, useState } from 'react'
import { Activity, Download, PauseCircle, PlayCircle, RefreshCw, ShieldCheck, Wrench } from 'lucide-react'
import {
  getConfig,
  getGitLabHealth,
  getPortStatus,
  getSyncHistory,
  getSyncSchedule,
  pauseScheduler,
  resumeScheduler,
  validateConfig,
  type ConfigValidationResponse,
  type GitLabHealthResponse,
  type OrgConfig,
  type PortStatusResponse,
  type SchedulerState,
  type SyncHistoryRun,
} from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import {
  buildProviderCards,
  buildProviderRows,
  formatDuration,
  formatSettingsTimestamp,
  getSchedulerSectionStatusLabel,
  getSyncRunMeta,
  getSyncRunStats,
} from '../features/settings/settingsHelpers.js'
import { downloadCsv } from '../utils/export'

export default function SettingsPage() {
  const [config, setConfig] = useState<OrgConfig | null>(null)
  const [validation, setValidation] = useState<ConfigValidationResponse | null>(null)
  const [gitlabHealth, setGitlabHealth] = useState<GitLabHealthResponse | null>(null)
  const [portStatus, setPortStatus] = useState<PortStatusResponse | null>(null)
  const [schedule, setSchedule] = useState<SchedulerState | null>(null)
  const [history, setHistory] = useState<SyncHistoryRun[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [validating, setValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = (refresh = false) => {
    if (refresh) setRefreshing(true)
    else setLoading(true)

    Promise.all([
      getConfig(),
      getGitLabHealth(),
      getPortStatus(),
      getSyncSchedule(),
      getSyncHistory(undefined, 20),
    ])
      .then(([configRes, gitlabRes, portRes, scheduleRes, historyRes]) => {
        setConfig(configRes.data)
        setGitlabHealth(gitlabRes.data)
        setPortStatus(portRes.data)
        setSchedule(scheduleRes.data)
        setHistory(historyRes.data.runs)
        setError(null)
      })
      .catch(err => setError(err?.message ?? 'Failed to load settings'))
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }

  useEffect(() => {
    load()
  }, [])

  const runValidation = async () => {
    setValidating(true)
    try {
      const res = await validateConfig()
      setValidation(res.data)
      setError(null)
    } catch (err: unknown) {
      const message = err && typeof err === 'object' && 'message' in err ? String(err.message) : 'Validation failed'
      setError(message)
    } finally {
      setValidating(false)
    }
  }

  const toggleScheduler = async () => {
    if (!schedule) return
    try {
      if (schedule.scheduler.paused) {
        await resumeScheduler()
      } else {
        await pauseScheduler()
      }
      await load(true)
    } catch (err: unknown) {
      const message = err && typeof err === 'object' && 'message' in err ? String(err.message) : 'Failed to update scheduler'
      setError(message)
    }
  }

  const providerCards = useMemo(
    () => buildProviderCards({ validation, gitlabHealth, portStatus }),
    [gitlabHealth, portStatus, validation],
  )

  if (loading) return <LoadingSpinner text="Loading settings..." />

  return (
    <div className="p-6 space-y-6">
      <div className="rounded-2xl border border-emerald-500/20 bg-[radial-gradient(circle_at_top_right,_rgba(16,185,129,0.14),_transparent_36%),linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(2,6,23,0.96))] p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-emerald-200">
              <Wrench size={12} />
              Settings & Health
            </div>
            <div>
              <h2 className="text-2xl font-semibold text-white">Provider health, scheduler control, and config visibility</h2>
              <p className="max-w-2xl text-sm leading-6 text-slate-300">
                Secrets remain environment-backed, but this page lets you validate providers, inspect sync posture, and export a clean operational snapshot.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => downloadCsv('provider-health.csv', buildProviderRows(providerCards))}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
            >
              <Download size={15} />
              Export health CSV
            </button>
            <button
              onClick={() => load(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:opacity-50"
            >
              <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
              Refresh
            </button>
            <button
              onClick={runValidation}
              disabled={validating}
              className="inline-flex items-center gap-2 rounded-xl bg-emerald-400 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-300 disabled:opacity-50"
            >
              <ShieldCheck size={15} />
              {validating ? 'Validating...' : 'Validate providers'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-white">
            <ShieldCheck size={16} className="text-emerald-300" />
            Provider health
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {providerCards.map(card => (
              <div key={card.label} className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
                <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">{card.label}</p>
                <p className={`mt-3 text-lg font-semibold ${card.ok ? 'text-emerald-300' : 'text-amber-300'}`}>
                  {card.ok ? 'Healthy' : 'Needs attention'}
                </p>
                <p className="mt-1 text-sm text-slate-300">{card.detail}</p>
                {card.error && <p className="mt-2 text-xs text-red-300">{card.error}</p>}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-white">
            <Activity size={16} className="text-sky-300" />
            Scheduler
          </div>
          <div className="space-y-4">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">State</p>
              <p className="mt-3 text-lg font-semibold text-white">
                {schedule?.scheduler.paused ? 'Paused' : 'Running'}
              </p>
              <p className="mt-1 text-sm text-slate-300">
                Active syncs: {schedule?.scheduler.active_syncs.length ?? 0}
              </p>
              {schedule && schedule.scheduler.active_syncs.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {schedule.scheduler.active_syncs.map(section => (
                    <span
                      key={section}
                      className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-sky-200"
                    >
                      {section}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={toggleScheduler}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
            >
              {schedule?.scheduler.paused ? <PlayCircle size={15} /> : <PauseCircle size={15} />}
              {schedule?.scheduler.paused ? 'Resume scheduler' : 'Pause scheduler'}
            </button>
            <div className="grid gap-2 text-sm text-slate-300">
              {Object.values(schedule?.sections ?? {}).map(section => (
                <div key={section.section} className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-white">{section.section}</span>
                    <span className={section.status === 'error' ? 'text-red-300' : 'text-slate-400'}>
                      {getSchedulerSectionStatusLabel(section)}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-slate-400 md:grid-cols-2">
                    <span>Last sync: {formatSettingsTimestamp(section.last_synced_at)}</span>
                    <span>Next due: {formatSettingsTimestamp(section.next_sync_at)}</span>
                    <span>Records: {section.records_synced}</span>
                    <span>Duration: {formatDuration(section.duration_seconds)}</span>
                    <span>Retries: {section.retry_count ?? 0}</span>
                    <span>{section.is_stale ? 'Needs refresh' : 'Within TTL'}</span>
                  </div>
                  {section.error && (
                    <p className="mt-2 text-xs text-red-300">{section.error}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Organization snapshot</p>
          <h3 className="mt-3 text-xl font-semibold text-white">{config?.organization.name ?? 'Unknown organization'}</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Domain slug</p>
              <p className="mt-2 text-sm text-slate-200">{config?.organization.slug ?? '—'}</p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Configured teams</p>
              <p className="mt-2 text-sm text-slate-200">{config?.teams.length ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">User</p>
              <p className="mt-2 text-sm text-slate-200">{config?.user?.name ?? '—'}</p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Jira site</p>
              <p className="mt-2 text-sm text-slate-200">{config?.organization.atlassian_site_url ?? 'Not set'}</p>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Credential guidance</p>
          <div className="mt-3 space-y-3 text-sm leading-6 text-slate-300">
            <p>Secrets remain environment-backed. Use this page to validate providers and watch for drift, not to expose or edit secret values in the browser.</p>
            <p>Recommended next step: add a secure rotation flow plus validation history if multiple operators are going to use this app.</p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
        <div className="mb-4 flex items-center gap-2 text-sm font-medium text-white">
          <Activity size={16} className="text-fuchsia-300" />
          Sync audit trail
        </div>
        <div className="space-y-2">
          {history.length === 0 ? (
            <p className="text-sm text-slate-400">No sync runs recorded yet.</p>
          ) : (
            history.map(run => {
              const stats = getSyncRunStats(run)

              return (
                <div key={run.id} className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">
                        {run.section} · {run.status}
                      </p>
                      <p className="text-xs text-slate-500">{getSyncRunMeta(run)}</p>
                    </div>
                    <div className="text-right text-xs text-slate-400">
                      <p>{stats.records}</p>
                      <p>{stats.duration}</p>
                    </div>
                  </div>
                  {run.error && <p className="mt-2 text-xs text-red-300">{run.error}</p>}
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
