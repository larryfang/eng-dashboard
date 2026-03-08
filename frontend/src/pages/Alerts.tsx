import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { BellRing, CheckCircle2, Download, ExternalLink, RefreshCw, ShieldAlert } from 'lucide-react'
import { getAlertsSummary, updateAlertTriage, type AlertItem, type AlertsSummaryResponse } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { downloadCsv } from '../utils/export'

type AlertDraft = {
  owner: string
  note: string
  status: AlertItem['status']
}

const severityClasses = {
  warning: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
  critical: 'bg-red-500/15 text-red-300 border-red-500/30',
}

const statusClasses = {
  open: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  acknowledged: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  resolved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
}

const sourceLabels: Record<AlertItem['alert_type'], string> = {
  team_trend: 'Team trend',
  quiet_engineer: 'Quiet engineer',
  stalled_epic: 'Stalled epic',
}

function toDraft(alert: AlertItem): AlertDraft {
  return {
    owner: alert.owner ?? '',
    note: alert.note ?? '',
    status: alert.status,
  }
}

function buildExportRows(alerts: AlertItem[]) {
  return alerts.map(alert => ({
    key: alert.alert_key,
    source: sourceLabels[alert.alert_type],
    severity: alert.severity,
    status: alert.status,
    title: alert.title,
    entity: alert.entity_label,
    owner: alert.owner ?? '',
    note: alert.note ?? '',
    updated_at: alert.updated_at ?? '',
    route: alert.route ?? '',
  }))
}

export default function AlertsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [response, setResponse] = useState<AlertsSummaryResponse | null>(null)
  const [drafts, setDrafts] = useState<Record<string, AlertDraft>>({})
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const selectedSeverity = searchParams.get('severity') ?? ''
  const selectedStatus = searchParams.get('status') ?? ''
  const selectedTeam = searchParams.get('team') ?? ''

  const load = (refresh = false) => {
    if (refresh) setRefreshing(true)
    else setLoading(true)

    getAlertsSummary()
      .then(res => {
        setResponse(res.data)
        setDrafts(Object.fromEntries(res.data.alerts.map(alert => [alert.alert_key, toDraft(alert)])))
        setError(null)
      })
      .catch(err => setError(err?.message ?? 'Failed to load alerts'))
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }

  useEffect(() => {
    load()
  }, [])

  const filteredAlerts = useMemo(() => {
    const alerts = response?.alerts ?? []
    return alerts.filter(alert => {
      if (selectedSeverity && alert.severity !== selectedSeverity) return false
      if (selectedStatus && alert.status !== selectedStatus) return false
      if (selectedTeam) {
        const teamSlug = String(alert.metadata?.team_slug ?? '')
        const entityKey = String(alert.metadata?.entity_key ?? '')
        if (teamSlug !== selectedTeam && entityKey !== selectedTeam) return false
      }
      return true
    })
  }, [response, selectedSeverity, selectedStatus, selectedTeam])

  const cards = [
    { label: 'Open', value: filteredAlerts.filter(alert => alert.status === 'open').length, tone: 'text-orange-300' },
    { label: 'Acknowledged', value: filteredAlerts.filter(alert => alert.status === 'acknowledged').length, tone: 'text-blue-300' },
    { label: 'Resolved', value: filteredAlerts.filter(alert => alert.status === 'resolved').length, tone: 'text-emerald-300' },
    { label: 'Critical', value: filteredAlerts.filter(alert => alert.severity === 'critical').length, tone: 'text-red-300' },
  ]

  const handleFilterChange = (key: 'severity' | 'status', value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  const handleDraftChange = (alertKey: string, patch: Partial<AlertDraft>) => {
    setDrafts(prev => ({
      ...prev,
      [alertKey]: { ...prev[alertKey], ...patch },
    }))
  }

  const handleSave = async (alert: AlertItem) => {
    const draft = drafts[alert.alert_key]
    if (!draft) return

    setSavingKey(alert.alert_key)
    try {
      const res = await updateAlertTriage({
        alert_key: alert.alert_key,
        owner: draft.owner,
        note: draft.note,
        status: draft.status,
      })
      const updated = ('alert' in res.data ? res.data.alert : res.data) as AlertItem
      setResponse(prev => prev ? {
        ...prev,
        alerts: prev.alerts.map(item => item.alert_key === alert.alert_key ? updated : item),
      } : prev)
      setDrafts(prev => ({ ...prev, [alert.alert_key]: toDraft(updated) }))
    } catch (err: unknown) {
      const message = err && typeof err === 'object' && 'message' in err ? String(err.message) : 'Failed to update alert'
      setError(message)
    } finally {
      setSavingKey(null)
    }
  }

  if (loading) return <LoadingSpinner text="Loading alerts..." />

  return (
    <div className="p-6 space-y-6">
      <div className="rounded-2xl border border-amber-500/20 bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.16),_transparent_40%),linear-gradient(135deg,_rgba(17,24,39,0.96),_rgba(2,6,23,0.96))] p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-amber-200">
              <BellRing size={12} />
              Alerts Center
            </div>
            <div>
              <h2 className="text-2xl font-semibold text-white">Operational triage for engineering signals</h2>
              <p className="max-w-2xl text-sm leading-6 text-slate-300">
                Assign owners, acknowledge issues, resolve noise, and jump straight into the underlying team, engineer, or epic context.
              </p>
            </div>
            {response?.generated_at && (
              <p className="text-xs text-slate-400">
                Generated {formatDistanceToNow(new Date(response.generated_at), { addSuffix: true })}
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => downloadCsv('alerts-center.csv', buildExportRows(filteredAlerts))}
              disabled={filteredAlerts.length === 0}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:opacity-40"
            >
              <Download size={15} />
              Export CSV
            </button>
            <button
              onClick={() => load(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl bg-amber-400 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-amber-300 disabled:opacity-50"
            >
              <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
              {refreshing ? 'Refreshing...' : 'Refresh alerts'}
            </button>
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {cards.map(card => (
            <div key={card.label} className="rounded-2xl border border-white/5 bg-slate-950/55 p-4">
              <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">{card.label}</p>
              <p className={`mt-2 text-3xl font-semibold ${card.tone}`}>{card.value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={selectedSeverity}
          onChange={e => handleFilterChange('severity', e.target.value)}
          className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-amber-400 focus:outline-none"
        >
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
        </select>
        <select
          value={selectedStatus}
          onChange={e => handleFilterChange('status', e.target.value)}
          className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-amber-400 focus:outline-none"
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
        </select>
        {selectedTeam && (
          <button
            onClick={() => {
              const next = new URLSearchParams(searchParams)
              next.delete('team')
              setSearchParams(next, { replace: true })
            }}
            className="rounded-full border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-slate-500 hover:text-white"
          >
            Clear team filter: {selectedTeam}
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {filteredAlerts.length === 0 ? (
        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-12 text-center">
          <ShieldAlert size={28} className="mx-auto mb-3 text-slate-500" />
          <p className="text-base font-medium text-white">No alerts match the current filters</p>
          <p className="mt-1 text-sm text-slate-400">Try widening the filters or refresh the alert feed.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredAlerts.map(alert => {
            const draft = drafts[alert.alert_key] ?? toDraft(alert)
            const isSaving = savingKey === alert.alert_key

            return (
              <div key={alert.alert_key} className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 shadow-[0_20px_60px_rgba(2,6,23,0.35)]">
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] ${severityClasses[alert.severity]}`}>
                        {alert.severity}
                      </span>
                      <span className={`rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] ${statusClasses[alert.status]}`}>
                        {alert.status}
                      </span>
                      <span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                        {sourceLabels[alert.alert_type]}
                      </span>
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-white">{alert.title}</h3>
                      <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-300">{alert.description}</p>
                    </div>
                    <div className="flex flex-wrap gap-4 text-xs text-slate-400">
                      <span>Entity: <span className="text-slate-200">{alert.entity_label}</span></span>
                      {alert.metric && <span>Metric: <span className="text-slate-200">{alert.metric}</span></span>}
                      {alert.updated_at && (
                        <span>Updated {formatDistanceToNow(new Date(alert.updated_at), { addSuffix: true })}</span>
                      )}
                    </div>
                  </div>

                  {alert.route && (
                    <Link
                      to={alert.route}
                      className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
                    >
                      Open related data
                      <ExternalLink size={14} />
                    </Link>
                  )}
                </div>

                <div className="mt-5 grid gap-3 xl:grid-cols-[1.1fr_220px]">
                  <textarea
                    value={draft.note}
                    onChange={e => handleDraftChange(alert.alert_key, { note: e.target.value })}
                    rows={3}
                    placeholder="Resolution notes, context, or next action..."
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-amber-400 focus:outline-none"
                  />

                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <input
                      type="text"
                      value={draft.owner}
                      onChange={e => handleDraftChange(alert.alert_key, { owner: e.target.value })}
                      placeholder="Owner"
                      className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-amber-400 focus:outline-none"
                    />
                    <select
                      value={draft.status}
                      onChange={e => handleDraftChange(alert.alert_key, { status: e.target.value as AlertItem['status'] })}
                      className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-amber-400 focus:outline-none"
                    >
                      <option value="open">Open</option>
                      <option value="acknowledged">Acknowledged</option>
                      <option value="resolved">Resolved</option>
                    </select>
                    <button
                      onClick={() => handleSave(alert)}
                      disabled={isSaving}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-amber-300 disabled:opacity-50 sm:col-span-2 xl:col-span-1"
                    >
                      {isSaving ? (
                        <>
                          <RefreshCw size={14} className="animate-spin" />
                          Saving...
                        </>
                      ) : (
                        <>
                          <CheckCircle2 size={14} />
                          Save triage
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
