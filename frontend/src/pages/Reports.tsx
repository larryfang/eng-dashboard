import { useEffect, useMemo, useState } from 'react'
import { BellRing, Download, FileText, Printer, RefreshCw, Trash2 } from 'lucide-react'
import {
  createExecutiveDigest,
  createSavedView,
  deleteExecutiveDigest,
  deleteSavedView,
  getExecutiveDigests,
  getExecutiveReport,
  getSavedViews,
  runExecutiveDigest,
  updateExecutiveDigest,
  type ExecutiveDigest,
  type ExecutiveDigestRun,
  type ExecutiveReportResponse,
  type SavedView,
} from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import {
  buildDigestPayload,
  buildSavedViewPayload,
  createDefaultDigestDraft,
  formatReportTimestamp,
  getDigestRunMeta,
  getDigestRunTitle,
  getDigestScheduleLabel,
  type DigestDraft,
} from '../features/reports/reportingHelpers.js'
import { downloadText, printHtmlDocument } from '../utils/export'

export default function ReportsPage() {
  const [report, setReport] = useState<ExecutiveReportResponse | null>(null)
  const [views, setViews] = useState<SavedView[]>([])
  const [digests, setDigests] = useState<ExecutiveDigest[]>([])
  const [runs, setRuns] = useState<ExecutiveDigestRun[]>([])
  const [selectedViewId, setSelectedViewId] = useState<number | undefined>(undefined)
  const [includePulse, setIncludePulse] = useState(true)
  const [viewName, setViewName] = useState('')
  const [digestDraft, setDigestDraft] = useState<DigestDraft>(createDefaultDigestDraft)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [savingView, setSavingView] = useState(false)
  const [savingDigest, setSavingDigest] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = (refresh = false, nextViewId = selectedViewId, nextIncludePulse = includePulse) => {
    if (refresh) setRefreshing(true)
    else setLoading(true)

    Promise.all([
      getExecutiveReport(nextViewId, nextIncludePulse),
      getSavedViews(),
      getExecutiveDigests(),
    ])
      .then(([reportRes, viewsRes, digestsRes]) => {
        setReport(reportRes.data)
        setViews(viewsRes.data.views)
        setDigests(digestsRes.data.digests)
        setRuns(digestsRes.data.runs)
        setError(null)
      })
      .catch(err => setError(err?.message ?? 'Failed to load executive reporting'))
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }

  useEffect(() => {
    load()
  }, [])

  const activeView = useMemo(
    () => views.find(view => view.id === selectedViewId),
    [selectedViewId, views],
  )

  useEffect(() => {
    if (!activeView) return
    setIncludePulse(Boolean(activeView.config.include_pulse ?? true))
  }, [activeView])

  const refreshReport = (viewId = selectedViewId, pulse = includePulse) => {
    load(true, viewId, pulse)
  }

  const handleSaveView = async () => {
    const payload = buildSavedViewPayload(viewName, includePulse)
    if (!payload) return

    setSavingView(true)
    try {
      await createSavedView(payload)
      setViewName('')
      await load(true)
    } catch (err: unknown) {
      const message = err && typeof err === 'object' && 'message' in err ? String(err.message) : 'Failed to save view'
      setError(message)
    } finally {
      setSavingView(false)
    }
  }

  const handleCreateDigest = async () => {
    const payload = buildDigestPayload(digestDraft, { selectedViewId, includePulse })
    if (!payload) return

    setSavingDigest(true)
    try {
      await createExecutiveDigest(payload)
      setDigestDraft(createDefaultDigestDraft())
      await load(true)
    } catch (err: unknown) {
      const message = err && typeof err === 'object' && 'message' in err ? String(err.message) : 'Failed to create digest'
      setError(message)
    } finally {
      setSavingDigest(false)
    }
  }

  const handleToggleDigest = async (digest: ExecutiveDigest) => {
    await updateExecutiveDigest(digest.id, {
      name: digest.name,
      saved_view_id: digest.saved_view_id ?? null,
      recipients: digest.recipients,
      include_pulse: digest.include_pulse,
      frequency: digest.frequency,
      weekday: digest.weekday ?? null,
      hour_utc: digest.hour_utc,
      active: !digest.active,
    })
    await load(true)
  }

  if (loading) return <LoadingSpinner text="Loading executive reporting..." />

  return (
    <div className="p-6 space-y-6">
      <div className="rounded-2xl border border-fuchsia-500/20 bg-[radial-gradient(circle_at_top_right,_rgba(217,70,239,0.15),_transparent_38%),linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(2,6,23,0.96))] p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-fuchsia-200">
              <FileText size={12} />
              Executive Reporting
            </div>
            <div>
              <h2 className="text-2xl font-semibold text-white">Saved views, printable reports, and scheduled digests</h2>
              <p className="max-w-2xl text-sm leading-6 text-slate-300">
                Reports are generated from the live Jira executive report stack. Digests are stored on schedule and delivered when an email provider is configured.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => downloadText('executive-report.md', report?.markdown ?? '')}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
            >
              <Download size={15} />
              Markdown
            </button>
            <button
              onClick={() => downloadText('executive-report.html', report?.html ?? '', 'text/html;charset=utf-8;')}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
            >
              <Download size={15} />
              HTML
            </button>
            <button
              onClick={() => printHtmlDocument('Executive Report', report?.html ?? '')}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
            >
              <Printer size={15} />
              Export PDF
            </button>
            <button
              onClick={() => refreshReport()}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl bg-fuchsia-400 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-fuchsia-300 disabled:opacity-50"
            >
              <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
              {refreshing ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-white/5 bg-slate-950/55 p-4">
            <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Teams</p>
            <p className="mt-2 text-3xl font-semibold text-white">{report?.summary.teams ?? 0}</p>
          </div>
          <div className="rounded-2xl border border-white/5 bg-slate-950/55 p-4">
            <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Active Items</p>
            <p className="mt-2 text-3xl font-semibold text-white">{report?.summary.total_items ?? 0}</p>
          </div>
          <div className="rounded-2xl border border-white/5 bg-slate-950/55 p-4">
            <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">WIP Epics</p>
            <p className="mt-2 text-3xl font-semibold text-white">{report?.summary.wip_epics ?? 0}</p>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-white">Saved views</h3>
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={includePulse}
                  onChange={e => setIncludePulse(e.target.checked)}
                />
                Include pulse
              </label>
            </div>
            <div className="space-y-2">
              <div className="flex gap-2">
                <input
                  value={viewName}
                  onChange={e => setViewName(e.target.value)}
                  placeholder="Save current view"
                  className="flex-1 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-fuchsia-400 focus:outline-none"
                />
                <button
                  onClick={handleSaveView}
                  disabled={savingView}
                  className="rounded-xl bg-fuchsia-400 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-fuchsia-300 disabled:opacity-50"
                >
                  {savingView ? 'Saving...' : 'Save'}
                </button>
              </div>
              {views.map(view => (
                <div key={view.id} className={`rounded-xl border px-3 py-3 ${selectedViewId === view.id ? 'border-fuchsia-400/40 bg-fuchsia-500/10' : 'border-slate-800 bg-slate-900/60'}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">{view.name}</p>
                      <p className="text-xs text-slate-500">Updated {formatReportTimestamp(view.updated_at)}</p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setSelectedViewId(view.id)
                          setIncludePulse(Boolean(view.config.include_pulse ?? true))
                          refreshReport(view.id, Boolean(view.config.include_pulse ?? true))
                        }}
                        className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500 hover:text-white"
                      >
                        Use
                      </button>
                      <button
                        onClick={async () => {
                          await deleteSavedView(view.id)
                          if (selectedViewId === view.id) setSelectedViewId(undefined)
                          await load(true)
                        }}
                        className="rounded-lg border border-slate-700 px-2 py-1.5 text-slate-400 hover:border-red-500/40 hover:text-red-300"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium text-white">
              <BellRing size={16} className="text-fuchsia-300" />
              Scheduled digests
            </div>
            <div className="grid gap-3">
              <input
                value={digestDraft.name}
                onChange={e => setDigestDraft(prev => ({ ...prev, name: e.target.value }))}
                placeholder="Digest name"
                className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-fuchsia-400 focus:outline-none"
              />
              <input
                value={digestDraft.recipients}
                onChange={e => setDigestDraft(prev => ({ ...prev, recipients: e.target.value }))}
                placeholder="Recipients (comma separated, optional)"
                className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-fuchsia-400 focus:outline-none"
              />
              <div className="grid gap-3 md:grid-cols-3">
                <select
                  value={digestDraft.frequency}
                  onChange={e => setDigestDraft(prev => ({ ...prev, frequency: e.target.value as DigestDraft['frequency'] }))}
                  className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-fuchsia-400 focus:outline-none"
                >
                  <option value="weekly">Weekly</option>
                  <option value="daily">Daily</option>
                </select>
                <select
                  value={digestDraft.weekday}
                  onChange={e => setDigestDraft(prev => ({ ...prev, weekday: Number(e.target.value) }))}
                  disabled={digestDraft.frequency !== 'weekly'}
                  className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-fuchsia-400 focus:outline-none disabled:opacity-40"
                >
                  <option value={0}>Monday</option>
                  <option value={1}>Tuesday</option>
                  <option value={2}>Wednesday</option>
                  <option value={3}>Thursday</option>
                  <option value={4}>Friday</option>
                  <option value={5}>Saturday</option>
                  <option value={6}>Sunday</option>
                </select>
                <input
                  type="number"
                  min={0}
                  max={23}
                  value={digestDraft.hour_utc}
                  onChange={e => setDigestDraft(prev => ({ ...prev, hour_utc: Number(e.target.value) }))}
                  className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-fuchsia-400 focus:outline-none"
                />
              </div>
              <button
                onClick={handleCreateDigest}
                disabled={savingDigest}
                className="rounded-xl bg-fuchsia-400 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-fuchsia-300 disabled:opacity-50"
              >
                {savingDigest ? 'Creating...' : 'Create digest'}
              </button>
            </div>

            <div className="space-y-2">
              {digests.map(digest => (
                <div key={digest.id} className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">{digest.name}</p>
                      <p className="text-xs text-slate-500">{getDigestScheduleLabel(digest)}</p>
                      <p className="text-xs text-slate-500">Next run {formatReportTimestamp(digest.next_run_at)}</p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={async () => {
                          await runExecutiveDigest(digest.id)
                          await load(true)
                        }}
                        className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500 hover:text-white"
                      >
                        Run now
                      </button>
                      <button
                        onClick={async () => handleToggleDigest(digest)}
                        className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500 hover:text-white"
                      >
                        {digest.active ? 'Pause' : 'Resume'}
                      </button>
                      <button
                        onClick={async () => {
                          await deleteExecutiveDigest(digest.id)
                          await load(true)
                        }}
                        className="rounded-lg border border-slate-700 px-2 py-1.5 text-slate-400 hover:border-red-500/40 hover:text-red-300"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-medium text-white">Report preview</h3>
                <p className="text-xs text-slate-500">Generated {formatReportTimestamp(report?.summary.generated_at)}</p>
              </div>
              {activeView && (
                <span className="rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-fuchsia-200">
                  {activeView.name}
                </span>
              )}
            </div>
            <div className="overflow-hidden rounded-xl border border-slate-800 bg-white">
              <iframe
                title="Executive report preview"
                srcDoc={report?.html ?? ''}
                className="h-[780px] w-full bg-white"
              />
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
            <h3 className="text-sm font-medium text-white">Recent digest runs</h3>
            <div className="mt-4 space-y-2">
              {runs.length === 0 ? (
                <p className="text-sm text-slate-400">No digest runs yet.</p>
              ) : (
                runs.map(run => (
                  <div key={run.id} className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm text-white">{getDigestRunTitle(run)}</p>
                        <p className="text-xs text-slate-500">{getDigestRunMeta(run)}</p>
                        {run.error_message && <p className="mt-1 text-xs text-amber-300">{run.error_message}</p>}
                      </div>
                      <div className="flex gap-2">
                        {run.report_markdown && (
                          <button
                            onClick={() => downloadText(`digest-run-${run.id}.md`, run.report_markdown ?? '')}
                            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500 hover:text-white"
                          >
                            Markdown
                          </button>
                        )}
                        {run.report_html && (
                          <button
                            onClick={() => printHtmlDocument(run.subject ?? `Digest ${run.id}`, run.report_html ?? '')}
                            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500 hover:text-white"
                          >
                            PDF
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
