import type {
  ConfigValidationResponse,
  CodePlatformHealthResponse,
  PortStatusResponse,
  SchedulerState,
  SyncHistoryRun,
} from '../../api/client.js'

export type ProviderCard = {
  label: string
  ok: boolean
  detail: string
  error?: string | null
}

type SchedulerSection = SchedulerState['sections'][string]

export function formatSettingsTimestamp(value?: string | null, fallback = 'Not yet synced'): string {
  if (!value) return fallback

  return new Date(value).toLocaleString('en-AU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  return `${(seconds / 60).toFixed(1)}m`
}

export function buildProviderCards(input: {
  validation: ConfigValidationResponse | null
  gitlabHealth: CodePlatformHealthResponse | null
  portStatus: PortStatusResponse | null
}): ProviderCard[] {
  const { validation, gitlabHealth, portStatus } = input

  return [
    {
      label: 'Code Platform',
      ok: gitlabHealth?.status === 'ok' || validation?.gitlab?.ok === true,
      detail: gitlabHealth?.authenticated_as ?? validation?.gitlab?.user ?? 'Not validated yet',
      error: gitlabHealth?.error ?? validation?.gitlab?.error,
    },
    {
      label: 'Jira API',
      ok: validation?.jira?.ok === true,
      detail: validation?.jira?.user ?? 'Run validation to confirm Jira access',
      error: validation?.jira?.error,
    },
    {
      label: 'Port.io',
      ok: Boolean(portStatus?.configured && portStatus?.connected),
      detail: portStatus?.configured ? 'Configured for service catalog sync' : 'Not configured',
      error: portStatus?.error,
    },
    {
      label: 'Email delivery',
      ok: validation?.email?.ok === true,
      detail: validation?.email?.user
        ?? (validation?.email?.provider ? `${validation.email.provider} configured` : 'Not configured'),
      error: validation?.email?.error,
    },
  ]
}

export function buildProviderRows(cards: ProviderCard[]) {
  return cards.map(card => ({
    provider: card.label,
    ok: card.ok ? 'yes' : 'no',
    detail: card.detail,
    error: card.error ?? '',
  }))
}

export function getSchedulerSectionStatusLabel(section: Pick<SchedulerSection, 'status' | 'is_active'>): string {
  return section.is_active ? 'running' : section.status
}

export function getSyncRunMeta(run: Pick<SyncHistoryRun, 'trigger_source' | 'period_days' | 'started_at'>): string {
  return `${run.trigger_source} · ${run.period_days}d · started ${formatSettingsTimestamp(run.started_at)}`
}

export function getSyncRunStats(run: Pick<SyncHistoryRun, 'records_synced' | 'duration_seconds'>) {
  return {
    records: `${run.records_synced} records`,
    duration: formatDuration(run.duration_seconds),
  }
}
