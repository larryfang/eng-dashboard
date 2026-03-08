import axios from 'axios'

export const api = axios.create({ baseURL: '/api' })

export interface TeamConfig {
  key: string
  name: string
  slug?: string
  scrum_name?: string
  headcount: number
  gitlab_path?: string
  jira_project?: string
  port_team_id?: string
}

export interface OrgConfig {
  organization: {
    name: string
    slug: string
    atlassian_site_url?: string
  }
  user?: {
    name: string
    email: string
    role?: string
  }
  teams: TeamConfig[]
}

export interface JiraEpic {
  key: string
  project: string
  team: string | null
  summary: string
  status: string
  status_category: string | null
  priority: string | null
  assignee: string | null
  url: string | null
  progress_percent: number | null
  child_issues_total: number | null
  child_issues_done: number | null
  updated_date: string | null
  due_date: string | null
}

export interface Engineer {
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
}

export interface DORAMetrics {
  team: string
  dora_level: string
  deployment_frequency: { value: number; unit: string }
  lead_time: { value: number; unit: string }
  change_failure_rate: { value: number }
  time_to_restore: { value: number; unit: string }
}

export const getConfig = () => api.get<OrgConfig>('/config')
export const getEngineers = (team?: string, days = 30, compare = false) =>
  api.get<{ engineers: Engineer[] }>('/gitlab/engineers', { params: { team, days, compare } })
export const getEngineer = (username: string, days = 90) =>
  api.get('/gitlab/engineers/' + username, { params: { days } })
export const syncEngineer = (username: string, days = 90) =>
  api.post(`/gitlab/engineers/${username}/sync`, null, { params: { days } })
export const getTeamMetrics = (days = 30) => api.get('/gitlab/metrics', { params: { days } })
export const getTeamSummary = (days = 30) => api.get<{ teams: Record<string, number>; period_days: number }>('/gitlab/team-summary', { params: { days } })
export const getJiraEpics = (team?: string, status?: string) =>
  api.get<{ epics: JiraEpic[]; count: number }>('/jira/index/epics', { params: { team, status } })

export interface EpicMR {
  title: string
  branch: string | null
  state: string
  created_at: string | null
  merged_at: string | null
  cycle_time_hours: number | null
  web_url: string | null
  lines_added: number | null
  lines_removed: number | null
  files_changed: number | null
}

export interface EpicContributor {
  username: string
  name: string
  team_display: string
  mr_count: number
  merged_count: number
  open_count: number
  branches: string[]
  avg_cycle_days: number | null
  calendar_days: number | null
  first_activity: string | null
  last_activity: string | null
  mrs: EpicMR[]
}

export const getEpicContributors = (epicKey: string) =>
  api.get<{ epic_key: string; contributors: EpicContributor[]; mr_count: number; engineer_count: number }>(
    `/jira/index/epics/${epicKey}/contributors`
  )
export const syncJira = (force_full = false) =>
  api.post('/jira/index/sync', null, { params: { force_full } })
export const getPortServices = () => api.get('/port/services')
export const syncPortServices = () => api.post('/port/sync')
export const enrichPortVersions = () => api.post('/port/enrich-versions')
export interface ProviderValidationResult {
  ok: boolean
  user: string | null
  error: string | null
  provider?: string | null
}

export interface ConfigValidationResponse {
  jira: ProviderValidationResult
  gitlab: ProviderValidationResult
  port: ProviderValidationResult | null
  email: ProviderValidationResult
}

export const validateConfig = () => api.post<ConfigValidationResponse>('/config/validate')
export const saveConfig = (config: unknown) => api.post('/config', config)
export const getSyncStatus = () => api.get('/sync/status')
export const getSectionSyncStatus = (section: string, days: number) =>
  api.get(`/sync/status/${section}`, { params: { days } })
export const triggerSync = (section: string, days: number, force_full = false) =>
  api.post(`/sync/${section}`, null, { params: { days, force_full } })

// Scheduler
export interface SchedulerState {
  scheduler: {
    running: boolean
    paused: boolean
    active_syncs: string[]
    retry_counts: Record<string, number>
  }
  sections: Record<string, {
    section: string
    period_days?: number
    status: string
    last_synced_at: string | null
    next_sync_at: string | null
    records_synced: number
    duration_seconds?: number | null
    is_stale: boolean
    error: string | null
    is_active: boolean
    retry_count?: number
  }>
}
export const getSyncSchedule = () => api.get<SchedulerState>('/sync/schedule')
export const pauseScheduler = () => api.post('/sync/schedule/pause')
export const resumeScheduler = () => api.post('/sync/schedule/resume')
export interface SyncHistoryRun {
  id: number
  section: string
  period_days: number
  trigger_source: string
  status: string
  records_synced: number
  error: string | null
  started_at: string | null
  finished_at: string | null
  duration_seconds?: number | null
}
export const getSyncHistory = (section?: string, limit = 30) =>
  api.get<{ runs: SyncHistoryRun[] }>('/sync/history', { params: { section, limit } })

export interface GitLabHealthResponse {
  status: string
  gitlab_url?: string | null
  authenticated_as?: string | null
  error?: string | null
}

export interface PortStatusResponse {
  configured: boolean
  connected: boolean
  error?: string | null
  token_expires_at?: string | null
}

export const getGitLabHealth = () => api.get<GitLabHealthResponse>('/gitlab/health')
export const getPortStatus = () => api.get<PortStatusResponse>('/port/status')
export interface MergeRequestActivityItem {
  id: string
  repo_id: string
  mr_iid: number
  title: string
  author_username: string
  team?: string | null
  state: string
  source_branch?: string | null
  created_at?: string | null
  merged_at?: string | null
  cycle_time_hours?: number | null
  web_url?: string | null
  jira_tickets?: string | null
  epic_keys?: string | null
}

export interface MergeRequestActivityResponse {
  filters: {
    team?: string | null
    engineer?: string | null
    epic?: string | null
    state?: string | null
    days: number
    compare: boolean
  }
  mrs?: MergeRequestActivityItem[]
  count?: number
  current?: MergeRequestActivityItem[]
  previous?: MergeRequestActivityItem[]
  current_count?: number
  previous_count?: number
}

export const getMergeRequestActivity = (params: {
  team?: string
  engineer?: string
  epic?: string
  state?: string
  days?: number
  compare?: boolean
  limit?: number
}) => api.get<MergeRequestActivityResponse>('/gitlab/activity', { params })

export interface AlertItem {
  alert_key: string
  alert_type: 'team_trend' | 'quiet_engineer' | 'stalled_epic'
  severity: 'warning' | 'critical'
  status: 'open' | 'acknowledged' | 'resolved'
  title: string
  description: string
  entity_type: 'team' | 'engineer' | 'epic'
  entity_label: string
  owner?: string | null
  note?: string | null
  route?: string | null
  metric?: string | null
  metadata?: Record<string, unknown>
  updated_at?: string | null
  resolved_at?: string | null
}

export interface AlertsSummaryResponse {
  generated_at: string
  alerts: AlertItem[]
  team_trends: Record<string, unknown>[] | { error: string }
  quiet_engineers: Record<string, unknown>[] | { error: string }
  stalled_epics: Record<string, unknown>[] | { error: string }
  summary: {
    teams_flagged: number
    quiet_engineer_count: number
    stalled_epic_count: number
    open_count?: number
    acknowledged_count?: number
    resolved_count?: number
    critical_count?: number
    warning_count?: number
  }
}

export interface AlertTriageUpdateRequest {
  alert_key: string
  status?: 'open' | 'acknowledged' | 'resolved'
  owner?: string
  note?: string
}

export type AlertTriageUpdateResponse = AlertItem | { alert: AlertItem }

export const getAlertsSummary = () => api.get<AlertsSummaryResponse>('/alerts/summary')
export const updateAlertTriage = (payload: AlertTriageUpdateRequest) =>
  api.post<AlertTriageUpdateResponse>('/alerts/triage', payload)

export interface SavedView {
  id: number
  name: string
  view_type: string
  config: Record<string, unknown>
  created_at?: string | null
  updated_at?: string | null
}

export interface ExecutiveDigest {
  id: number
  name: string
  saved_view_id?: number | null
  recipients: string[]
  include_pulse: boolean
  frequency: 'daily' | 'weekly'
  weekday?: number | null
  hour_utc: number
  active: boolean
  last_run_at?: string | null
  next_run_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface ExecutiveDigestRun {
  id: number
  digest_id: number
  status: string
  delivery_state: string
  recipient_count: number
  subject?: string | null
  error_message?: string | null
  generated_at?: string | null
  report_markdown?: string | null
  report_html?: string | null
}

export interface ExecutiveReportResponse {
  view_id?: number | null
  config: Record<string, unknown>
  html: string
  markdown: string
  summary: {
    teams: number
    total_items: number
    wip_epics: number
    generated_at: string
  }
}

export const getExecutiveReport = (viewId?: number, includePulse?: boolean) =>
  api.get<ExecutiveReportResponse>('/reports/executive', { params: { view_id: viewId, include_pulse: includePulse } })
export const getSavedViews = (viewType = 'executive_report') =>
  api.get<{ views: SavedView[] }>('/reports/views', { params: { view_type: viewType } })
export const createSavedView = (payload: { name: string; view_type?: string; config: Record<string, unknown> }) =>
  api.post<SavedView>('/reports/views', payload)
export const updateSavedView = (id: number, payload: { name: string; view_type?: string; config: Record<string, unknown> }) =>
  api.put<SavedView>(`/reports/views/${id}`, payload)
export const deleteSavedView = (id: number) => api.delete(`/reports/views/${id}`)
export const getExecutiveDigests = () =>
  api.get<{ digests: ExecutiveDigest[]; runs: ExecutiveDigestRun[] }>('/reports/digests')
export const createExecutiveDigest = (payload: {
  name: string
  saved_view_id?: number | null
  recipients: string[]
  include_pulse: boolean
  frequency: 'daily' | 'weekly'
  weekday?: number | null
  hour_utc: number
  active: boolean
}) => api.post<ExecutiveDigest>('/reports/digests', payload)
export const updateExecutiveDigest = (id: number, payload: {
  name: string
  saved_view_id?: number | null
  recipients: string[]
  include_pulse: boolean
  frequency: 'daily' | 'weekly'
  weekday?: number | null
  hour_utc: number
  active: boolean
}) => api.put<ExecutiveDigest>(`/reports/digests/${id}`, payload)
export const deleteExecutiveDigest = (id: number) => api.delete(`/reports/digests/${id}`)
export const runExecutiveDigest = (id: number) =>
  api.post<{ run: ExecutiveDigestRun; digest: ExecutiveDigest }>(`/reports/digests/${id}/run`)

// Search
export interface SearchResult {
  type: 'engineer' | 'team' | 'mr' | 'epic' | 'service'
  id: string
  title: string
  subtitle: string
  url: string | null
  external_url?: string
}

export interface SearchResponse {
  query: string
  results: Record<string, SearchResult[]>
  total: number
}

export const globalSearch = (q: string, signal?: AbortSignal, limit = 5) =>
  api.get<SearchResponse>('/search', { params: { q, limit }, signal })

// Trending
export interface TeamTrend {
  team: string
  buckets: { date: string; mrs: number }[]
}
export const getTeamSummaryWithCompare = (days = 30) =>
  api.get<{
    teams: Record<string, number>
    period_days: number
    deltas?: Record<string, { current: number; previous: number; delta: number; pct_change: number | null }>
  }>('/gitlab/team-summary', { params: { days, compare: true } })
export const getTeamTrend = (team: string, days = 90) =>
  api.get<TeamTrend>('/gitlab/team-trend', { params: { team, days } })
