import type { ExecutiveDigest, ExecutiveDigestRun } from '../../api/client.js'

export type DigestDraft = {
  name: string
  recipients: string
  frequency: 'daily' | 'weekly'
  weekday: number
  hour_utc: number
}

export type SavedViewPayload = {
  name: string
  view_type: 'executive_report'
  config: {
    include_pulse: boolean
    format: 'html'
  }
}

export type DigestPayload = {
  name: string
  saved_view_id: number | null
  recipients: string[]
  include_pulse: boolean
  frequency: 'daily' | 'weekly'
  weekday: number | null
  hour_utc: number
  active: true
}

export function createDefaultDigestDraft(): DigestDraft {
  return {
    name: 'Weekly Executive Digest',
    recipients: '',
    frequency: 'weekly',
    weekday: 0,
    hour_utc: 8,
  }
}

export function formatReportTimestamp(value?: string | null, fallback = '—'): string {
  if (!value) return fallback

  return new Date(value).toLocaleString('en-AU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function parseDigestRecipients(value: string): string[] {
  return value
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
}

function normalizeHourUtc(value: number): number {
  if (!Number.isFinite(value)) return 8
  return Math.min(23, Math.max(0, Math.trunc(value)))
}

function normalizeWeekday(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(6, Math.max(0, Math.trunc(value)))
}

export function buildSavedViewPayload(name: string, includePulse: boolean): SavedViewPayload | null {
  const trimmedName = name.trim()
  if (!trimmedName) return null

  return {
    name: trimmedName,
    view_type: 'executive_report',
    config: {
      include_pulse: includePulse,
      format: 'html',
    },
  }
}

export function buildDigestPayload(
  draft: DigestDraft,
  options: { selectedViewId?: number; includePulse: boolean },
): DigestPayload | null {
  const trimmedName = draft.name.trim()
  if (!trimmedName) return null

  return {
    name: trimmedName,
    saved_view_id: options.selectedViewId ?? null,
    recipients: parseDigestRecipients(draft.recipients),
    include_pulse: options.includePulse,
    frequency: draft.frequency,
    weekday: draft.frequency === 'weekly' ? normalizeWeekday(draft.weekday) : null,
    hour_utc: normalizeHourUtc(draft.hour_utc),
    active: true,
  }
}

export function getDigestScheduleLabel(
  digest: Pick<ExecutiveDigest, 'frequency' | 'hour_utc' | 'weekday'>,
): string {
  const hour = String(normalizeHourUtc(digest.hour_utc)).padStart(2, '0')
  const weekday = digest.frequency === 'weekly' && digest.weekday != null
    ? ` · weekday ${normalizeWeekday(digest.weekday)}`
    : ''

  return `${digest.frequency} at ${hour}:00 UTC${weekday}`
}

export function getDigestRunTitle(run: Pick<ExecutiveDigestRun, 'id' | 'subject'>): string {
  return run.subject ?? `Digest run #${run.id}`
}

export function getDigestRunMeta(
  run: Pick<ExecutiveDigestRun, 'generated_at' | 'delivery_state' | 'recipient_count'>,
): string {
  return `${formatReportTimestamp(run.generated_at)} · ${run.delivery_state} · ${run.recipient_count} recipients`
}
