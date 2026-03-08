import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'
import {
  AlertCircle,
  ArrowRight,
  Building2,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FolderGit2,
  KeyRound,
  Loader2,
  Plus,
  RefreshCcw,
  Rocket,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Users,
} from 'lucide-react'

interface SetupProps {
  onComplete: () => void
  isNewDomain?: boolean
}

type Step = 'basics' | 'connections' | 'teams' | 'review' | 'syncing'

type MemberRole = 'TL' | 'engineer' | 'observer'

interface OrgForm {
  name: string
  slug: string
  description: string
}

interface UserForm {
  name: string
  email: string
  role: string
  timezone: string
}

interface GitLabForm {
  url: string
  token: string
  baseGroup: string
}

interface JiraForm {
  url: string
  email: string
  token: string
}

interface OptionalForm {
  portClientId: string
  portClientSecret: string
  portBaseUrl: string
  snykToken: string
}

type CodePlatform = 'none' | 'gitlab' | 'github'
type IssueTracker = 'none' | 'jira' | 'linear' | 'monday' | 'asana'
type AiProvider = 'none' | 'openai' | 'anthropic'
type SecurityProvider = 'none' | 'snyk'

interface GitHubForm {
  token: string
  org: string
}

interface LinearForm {
  apiKey: string
}

interface MondayForm {
  token: string
}

interface AsanaForm {
  token: string
}

interface AiForm {
  openaiKey: string
  anthropicKey: string
}

interface Member {
  username: string
  name: string
  email: string
  role: MemberRole
}

interface TeamForm {
  jiraKey: string
  name: string
  slug: string
  scrumName: string
  lead: string
  leadEmail: string
  gitlabPath: string
  members: Member[]
}

interface ValidationResult {
  gitlab?: { ok: boolean; user?: string; error?: string } | null
  github?: { ok: boolean; user?: string; error?: string } | null
  jira?: { ok: boolean; user?: string; error?: string } | null
  linear?: { ok: boolean; user?: string; error?: string } | null
  monday?: { ok: boolean; user?: string; error?: string } | null
  asana?: { ok: boolean; user?: string; error?: string } | null
  openai?: { ok: boolean; user?: string; error?: string } | null
  anthropic?: { ok: boolean; user?: string; error?: string } | null
  snyk?: { ok: boolean; user?: string; error?: string } | null
}

interface GitLabGroup {
  id: number
  name: string
  full_path: string
  description?: string
}

interface JiraProject {
  key: string
  name: string
  type?: string
}

interface SyncSectionStatus {
  status: string
  last_synced_at?: string | null
  next_sync_at?: string | null
  error?: string | null
  is_active?: boolean
  retry_count?: number
}

interface SyncScheduleResponse {
  sections?: Record<string, SyncSectionStatus>
}

const STEPS: Array<{ key: Exclude<Step, 'syncing'>; label: string; hint: string }> = [
  { key: 'basics', label: 'Basics', hint: 'Name the domain and owner' },
  { key: 'connections', label: 'Connections', hint: 'Connect your tools (all optional)' },
  { key: 'teams', label: 'Teams', hint: 'Discover squads and members' },
  { key: 'review', label: 'Review', hint: 'Create and start syncing' },
]

function toSlug(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function titleFromSlug(value: string) {
  if (!value) return ''
  return value
    .split(/[-_]+/)
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function normaliseRole(raw: string | undefined): MemberRole {
  const value = (raw || '').trim().toLowerCase()
  if (value === 'tl' || value === 'tech lead' || value === 'maintainer' || value === 'owner') {
    return 'TL'
  }
  if (value === 'observer' || value === 'reporter' || value === 'guest') {
    return 'observer'
  }
  return 'engineer'
}

function formatTimestamp(value?: string | null) {
  if (!value) return 'Not yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Not yet'
  return date.toLocaleString()
}

function ValidationBadge({
  label,
  result,
}: {
  label: string
  result: { ok: boolean; user?: string; error?: string } | null | undefined
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="text-slate-400">{label}</span>
        {!result ? (
          <span className="text-slate-500">Not checked</span>
        ) : result.ok ? (
          <span className="inline-flex items-center gap-1 text-emerald-300">
            <CheckCircle2 size={12} />
            {result.user || 'Connected'}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-rose-300">
            <AlertCircle size={12} />
            {result.error || 'Validation failed'}
          </span>
        )}
      </div>
    </div>
  )
}

function StepRail({
  current,
  onSelect,
}: {
  current: Exclude<Step, 'syncing'>
  onSelect: (step: Exclude<Step, 'syncing'>) => void
}) {
  const currentIndex = STEPS.findIndex(step => step.key === current)

  return (
    <div className="rounded-3xl border border-slate-800 bg-slate-900/85 p-5 shadow-[0_24px_80px_rgba(2,12,27,0.45)] backdrop-blur">
      <div className="mb-5 flex items-center gap-3">
        <div className="rounded-2xl bg-cyan-500/10 p-2 text-cyan-300">
          <Sparkles size={16} />
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Onboarding flow</p>
          <h2 className="text-sm font-semibold text-white">Critical path setup</h2>
        </div>
      </div>

      <div className="space-y-3">
        {STEPS.map((step, index) => {
          const isDone = index < currentIndex
          const isActive = index === currentIndex
          return (
            <button
              key={step.key}
              type="button"
              onClick={() => onSelect(step.key)}
              className={`rounded-2xl border px-4 py-3 transition-colors ${
                isActive
                  ? 'border-cyan-500/50 bg-cyan-500/8'
                  : isDone
                    ? 'border-emerald-500/25 bg-emerald-500/8'
                    : 'border-slate-800 bg-slate-950/70'
              } w-full text-left hover:border-cyan-500/35 hover:bg-slate-900/85`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`mt-0.5 flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                    isDone
                      ? 'bg-emerald-500 text-slate-950'
                      : isActive
                        ? 'bg-cyan-400 text-slate-950'
                        : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {isDone ? <Check size={14} /> : index + 1}
                </div>
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${isActive ? 'text-white' : 'text-slate-300'}`}>{step.label}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{step.hint}</p>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function SyncStatusCard({
  section,
  status,
}: {
  section: string
  status?: SyncSectionStatus
}) {
  const value = status?.status || 'idle'
  const tone =
    value === 'success'
      ? 'text-emerald-300 border-emerald-500/25 bg-emerald-500/10'
      : value === 'error'
        ? 'text-rose-300 border-rose-500/25 bg-rose-500/10'
        : value === 'syncing'
          ? 'text-cyan-300 border-cyan-500/25 bg-cyan-500/10'
          : 'text-slate-400 border-slate-800 bg-slate-950/70'

  return (
    <div className={`rounded-2xl border p-4 ${tone}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">{section}</p>
          <p className="mt-1 text-xs capitalize">{value}</p>
        </div>
        {value === 'syncing' ? <Loader2 size={14} className="animate-spin" /> : null}
      </div>
      <p className="mt-3 text-xs text-slate-400">Last sync: {formatTimestamp(status?.last_synced_at)}</p>
      {status?.error ? <p className="mt-2 text-xs text-rose-300">{status.error}</p> : null}
    </div>
  )
}

function TeamEditor({
  team,
  index,
  projectOptions,
  onChange,
  onRemove,
  onDiscoverMembers,
  discoveringMembers,
  memberError,
}: {
  team: TeamForm
  index: number
  projectOptions: JiraProject[]
  onChange: (next: TeamForm) => void
  onRemove: () => void
  onDiscoverMembers: () => void
  discoveringMembers: boolean
  memberError?: string
}) {
  const setTeam = (patch: Partial<TeamForm>) => onChange({ ...team, ...patch })

  const updateMember = (memberIndex: number, patch: Partial<Member>) => {
    const nextMembers = [...team.members]
    nextMembers[memberIndex] = { ...nextMembers[memberIndex], ...patch }
    setTeam({ members: nextMembers })
  }

  const addMember = () => {
    setTeam({
      members: [...team.members, { username: '', name: '', email: '', role: 'engineer' }],
    })
  }

  const removeMember = (memberIndex: number) => {
    setTeam({ members: team.members.filter((_, idx) => idx !== memberIndex) })
  }

  return (
    <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Team {index + 1}</p>
          <h3 className="mt-1 text-lg font-semibold text-white">{team.name || 'Untitled team'}</h3>
          <p className="mt-1 text-xs text-slate-500">{team.gitlabPath || 'GitLab path not set yet'}</p>
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-slate-800 text-slate-400 transition-colors hover:border-rose-500/40 hover:text-rose-300"
          aria-label={`Remove ${team.name || `team ${index + 1}`}`}
        >
          <Trash2 size={14} />
        </button>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <label className="space-y-2 text-sm text-slate-300">
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Team name</span>
          <input
            className="setup-input"
            value={team.name}
            placeholder="Marketing Automation"
            onChange={event => {
              const nextName = event.target.value
              setTeam({
                name: nextName,
                slug: team.slug || toSlug(nextName),
                scrumName: team.scrumName || nextName,
              })
            }}
          />
        </label>
        <label className="space-y-2 text-sm text-slate-300">
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Slug</span>
          <input
            className="setup-input font-mono"
            value={team.slug}
            placeholder="marketing-automation"
            onChange={event => setTeam({ slug: toSlug(event.target.value) })}
          />
        </label>
        <label className="space-y-2 text-sm text-slate-300">
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">GitLab path</span>
          <input
            className="setup-input font-mono text-xs"
            value={team.gitlabPath}
            placeholder="acme/teams/platform"
            onChange={event => setTeam({ gitlabPath: event.target.value })}
          />
        </label>
        <label className="space-y-2 text-sm text-slate-300">
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Jira project</span>
          {projectOptions.length > 0 ? (
            <select
              className="setup-input"
              value={team.jiraKey}
              onChange={event => setTeam({ jiraKey: event.target.value })}
            >
              <option value="">Not linked yet</option>
              {projectOptions.map(project => (
                <option key={project.key} value={project.key}>
                  {project.key} - {project.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="setup-input font-mono"
              value={team.jiraKey}
              placeholder="MA"
              onChange={event => setTeam({ jiraKey: event.target.value.toUpperCase() })}
            />
          )}
        </label>
        <label className="space-y-2 text-sm text-slate-300">
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Squad name</span>
          <input
            className="setup-input"
            value={team.scrumName}
            placeholder="Phoenix"
            onChange={event => setTeam({ scrumName: event.target.value })}
          />
        </label>
        <label className="space-y-2 text-sm text-slate-300">
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Tech lead</span>
          <input
            className="setup-input"
            value={team.lead}
            placeholder="Jane Smith"
            onChange={event => setTeam({ lead: event.target.value })}
          />
        </label>
        <label className="space-y-2 text-sm text-slate-300">
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Lead email</span>
          <input
            className="setup-input"
            value={team.leadEmail}
            placeholder="jane.smith@company.com"
            onChange={event => setTeam({ leadEmail: event.target.value })}
          />
        </label>
      </div>

      <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-white">Team members</p>
            <p className="mt-1 text-xs text-slate-500">Pull inherited GitLab members or add them manually.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onDiscoverMembers}
              disabled={discoveringMembers || !team.gitlabPath}
              className="inline-flex items-center gap-2 rounded-2xl border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-medium text-cyan-200 transition-colors hover:border-cyan-400/60 hover:bg-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {discoveringMembers ? <Loader2 size={12} className="animate-spin" /> : <RefreshCcw size={12} />}
              Discover members
            </button>
            <button
              type="button"
              onClick={addMember}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
            >
              <Plus size={12} />
              Add member
            </button>
          </div>
        </div>

        {memberError ? (
          <div className="mt-3 rounded-2xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {memberError}
          </div>
        ) : null}

        {team.members.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-slate-800 px-4 py-5 text-sm text-slate-500">
            No members yet. Discover them from GitLab or add them manually.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {team.members.map((member, memberIndex) => (
              <div key={`${team.slug || index}-${member.username || memberIndex}`} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                <div className="grid gap-3 md:grid-cols-[1.2fr_1.4fr_1.6fr_0.8fr_auto]">
                  <input
                    className="setup-input font-mono text-xs"
                    value={member.username}
                    placeholder="gitlab.username"
                    onChange={event => updateMember(memberIndex, { username: event.target.value })}
                  />
                  <input
                    className="setup-input"
                    value={member.name}
                    placeholder="Full name"
                    onChange={event => updateMember(memberIndex, { name: event.target.value })}
                  />
                  <input
                    className="setup-input"
                    value={member.email}
                    placeholder="name@company.com"
                    onChange={event => updateMember(memberIndex, { email: event.target.value })}
                  />
                  <select
                    className="setup-input"
                    value={member.role}
                    onChange={event => updateMember(memberIndex, { role: event.target.value as MemberRole })}
                  >
                    <option value="engineer">Engineer</option>
                    <option value="TL">Tech lead</option>
                    <option value="observer">Observer</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => removeMember(memberIndex)}
                    className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-slate-800 text-slate-400 transition-colors hover:border-rose-500/40 hover:text-rose-300"
                    aria-label={`Remove ${member.name || member.username || 'member'}`}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Setup({ onComplete, isNewDomain = false }: SetupProps) {
  const [searchParams] = useSearchParams()
  const prefilledSlug = searchParams.get('slug') ?? searchParams.get('stub') ?? ''
  const prefilledName = searchParams.get('name') ?? ''
  const lockedSlug = Boolean(prefilledSlug) && !isNewDomain

  const [step, setStep] = useState<Step>('basics')
  const [org, setOrg] = useState<OrgForm>(() => ({
    name: prefilledName || titleFromSlug(prefilledSlug),
    slug: prefilledSlug,
    description: '',
  }))
  const [user, setUser] = useState<UserForm>(() => ({
    name: '',
    email: '',
    role: 'Engineering Manager',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  }))
  const [gitlab, setGitlab] = useState<GitLabForm>({
    url: 'https://gitlab.com',
    token: '',
    baseGroup: '',
  })
  const [jira, setJira] = useState<JiraForm>({ url: '', email: '', token: '' })
  const [optional, setOptional] = useState<OptionalForm>({
    portClientId: '',
    portClientSecret: '',
    portBaseUrl: 'https://api.getport.io',
    snykToken: '',
  })
  const [codePlatform, setCodePlatform] = useState<CodePlatform>('none')
  const [issueTracker, setIssueTracker] = useState<IssueTracker>('none')
  const [aiProvider, setAiProvider] = useState<AiProvider>('none')
  const [securityProvider, setSecurityProvider] = useState<SecurityProvider>('none')
  const [github, setGithub] = useState<GitHubForm>({ token: '', org: '' })
  const [linear, setLinear] = useState<LinearForm>({ apiKey: '' })
  const [monday, setMonday] = useState<MondayForm>({ token: '' })
  const [asana, setAsana] = useState<AsanaForm>({ token: '' })
  const [ai, setAi] = useState<AiForm>({ openaiKey: '', anthropicKey: '' })
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [teams, setTeams] = useState<TeamForm[]>([])
  const [discoveredGroups, setDiscoveredGroups] = useState<GitLabGroup[]>([])
  const [discoveredProjects, setDiscoveredProjects] = useState<JiraProject[]>([])
  const [discoveringGroups, setDiscoveringGroups] = useState(false)
  const [discoveringProjects, setDiscoveringProjects] = useState(false)
  const [bulkDiscoveringMembers, setBulkDiscoveringMembers] = useState(false)
  const [groupSearch, setGroupSearch] = useState('')
  const [groupsError, setGroupsError] = useState<string | null>(null)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [memberLoading, setMemberLoading] = useState<Record<string, boolean>>({})
  const [memberErrors, setMemberErrors] = useState<Record<string, string>>({})
  const [createError, setCreateError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [syncInfo, setSyncInfo] = useState<SyncScheduleResponse | null>(null)
  const [syncReady, setSyncReady] = useState(false)

  useEffect(() => {
    if (!prefilledSlug || prefilledName) return
    setOrg(current => ({
      ...current,
      name: current.name || titleFromSlug(prefilledSlug),
      slug: current.slug || prefilledSlug,
    }))
  }, [prefilledName, prefilledSlug])

  useEffect(() => {
    setValidation(null)
  }, [codePlatform, issueTracker, aiProvider, securityProvider, gitlab.token, gitlab.url, github.token, jira.url, jira.email, jira.token, linear.apiKey, monday.token, asana.token, ai.openaiKey, ai.anthropicKey, optional.snykToken])

  useEffect(() => {
    setDiscoveredGroups([])
    setGroupsError(null)
  }, [gitlab.baseGroup, gitlab.url])

  useEffect(() => {
    setDiscoveredProjects([])
    setProjectsError(null)
  }, [jira.url, jira.email, jira.token])

  const teamKey = (team: TeamForm, index: number) => team.slug || team.gitlabPath || `team-${index}`

  const jiraFullyConfigured = Boolean(jira.url.trim() && jira.email.trim() && jira.token.trim())

  const hasAnyConnection = Boolean(
    (codePlatform === 'gitlab' && gitlab.token.trim()) ||
    (codePlatform === 'github' && github.token.trim()) ||
    (issueTracker === 'jira' && jiraFullyConfigured) ||
    (issueTracker === 'linear' && linear.apiKey.trim()) ||
    (issueTracker === 'monday' && monday.token.trim()) ||
    (issueTracker === 'asana' && asana.token.trim()) ||
    (aiProvider === 'openai' && ai.openaiKey.trim()) ||
    (aiProvider === 'anthropic' && ai.anthropicKey.trim()) ||
    (securityProvider === 'snyk' && optional.snykToken.trim())
  )

  const filteredGroups = useMemo(() => {
    const query = groupSearch.trim().toLowerCase()
    if (!query) return discoveredGroups
    return discoveredGroups.filter(group =>
      [group.name, group.full_path, group.description || ''].some(value => value.toLowerCase().includes(query)),
    )
  }, [discoveredGroups, groupSearch])

  const incompleteTeams = useMemo(
    () => teams.filter(team => !team.name.trim() || !team.slug.trim()),
    [teams],
  )
  const teamsWithoutMembers = useMemo(
    () => teams.filter(team => team.members.length === 0),
    [teams],
  )

  const reviewWarnings = useMemo(() => {
    const warnings: string[] = []
    if (codePlatform === 'none') {
      warnings.push('No code platform connected. Engineer activity and MR metrics will be unavailable.')
    }
    if (issueTracker === 'none') {
      warnings.push('No issue tracker connected. Epic health and roadmap views will be unavailable.')
    }
    if (teamsWithoutMembers.length > 0) {
      warnings.push(`${teamsWithoutMembers.length} team${teamsWithoutMembers.length === 1 ? '' : 's'} still have no members.`)
    }
    if (aiProvider === 'none') {
      warnings.push('No AI provider connected. AI summaries and analysis will be unavailable.')
    }
    return warnings
  }, [codePlatform, issueTracker, aiProvider, teamsWithoutMembers.length])

  const currentStepIndex = Math.max(0, STEPS.findIndex(candidate => candidate.key === step))

  const canContinueBasics = Boolean(org.name.trim() && org.slug.trim())
  const canContinueConnections = true
  const canContinueTeams = teams.length > 0 && incompleteTeams.length === 0
  const readinessHint =
    step === 'basics' && !canContinueBasics
      ? 'Preview mode is enabled. Name and slug will still be required when you actually create the domain.'
      : step === 'connections' && !canContinueConnections
        ? 'Preview mode is enabled. Validation is advisory for navigation, but GitLab still needs to validate before create.'
        : step === 'teams' && !canContinueTeams
          ? 'Preview mode is enabled. You can inspect Review now, but at least one complete team is still required for a successful create.'
          : step === 'review'
            ? 'Create still uses the real backend validations. If required fields are missing, the API will reject the request.'
            : null

  const discoverGitLabGroups = async (silent = false) => {
    if (!gitlab.token.trim() || !gitlab.baseGroup.trim()) {
      if (!silent) setGroupsError('GitLab token and base group are required to discover teams.')
      return
    }

    setDiscoveringGroups(true)
    if (!silent) setGroupsError(null)
    try {
      const response = await axios.get('/api/onboard/discover/gitlab-groups', {
        params: { group_path: gitlab.baseGroup, gitlab_url: gitlab.url.trim() },
        headers: {
          'X-GitLab-Token': gitlab.token,
          'X-GitLab-Url': gitlab.url.trim(),
        },
      })
      setDiscoveredGroups(response.data.groups ?? [])
      if (!silent && (response.data.groups ?? []).length === 0) {
        setGroupsError('No subgroups were found under that GitLab base group.')
      }
    } catch (error: any) {
      const detail = error.response?.data?.detail ?? 'GitLab discovery failed'
      setGroupsError(detail)
    } finally {
      setDiscoveringGroups(false)
    }
  }

  const discoverJiraProjects = async (silent = false) => {
    if (!jiraFullyConfigured) {
      if (!silent) setProjectsError('Jira URL, email, and API token are all required to discover Jira projects.')
      return
    }

    setDiscoveringProjects(true)
    if (!silent) setProjectsError(null)
    try {
      const response = await axios.get('/api/onboard/discover/jira-projects', {
        params: { jira_url: jira.url.trim() },
        headers: {
          'X-Jira-Email': jira.email,
          'X-Jira-Token': jira.token,
        },
      })
      setDiscoveredProjects(response.data.projects ?? [])
      if (!silent && (response.data.projects ?? []).length === 0) {
        setProjectsError('Jira connected, but no software projects were returned.')
      }
    } catch (error: any) {
      const detail = error.response?.data?.detail ?? 'Jira project discovery failed'
      setProjectsError(detail)
    } finally {
      setDiscoveringProjects(false)
    }
  }

  const validateConnections = async () => {
    setValidating(true)
    setCreateError(null)
    setValidation(null)
    try {
      const payload: Record<string, string> = {}
      if (codePlatform === 'gitlab' && gitlab.token.trim()) {
        payload.gitlab_token = gitlab.token
        payload.gitlab_url = gitlab.url.trim()
      }
      if (codePlatform === 'github' && github.token.trim()) {
        payload.github_token = github.token
        if (github.org.trim()) payload.github_org = github.org.trim()
      }
      if (issueTracker === 'jira' && jira.url.trim() && jira.email.trim() && jira.token.trim()) {
        payload.jira_url = jira.url.trim()
        payload.jira_email = jira.email.trim()
        payload.jira_token = jira.token
      }
      if (issueTracker === 'linear' && linear.apiKey.trim()) {
        payload.linear_api_key = linear.apiKey
      }
      if (issueTracker === 'monday' && monday.token.trim()) {
        payload.monday_token = monday.token
      }
      if (issueTracker === 'asana' && asana.token.trim()) {
        payload.asana_token = asana.token
      }
      if (aiProvider === 'openai' && ai.openaiKey.trim()) {
        payload.openai_api_key = ai.openaiKey
      }
      if (aiProvider === 'anthropic' && ai.anthropicKey.trim()) {
        payload.anthropic_api_key = ai.anthropicKey
      }
      if (securityProvider === 'snyk' && optional.snykToken.trim()) {
        payload.snyk_token = optional.snykToken
      }

      if (Object.keys(payload).length === 0) {
        setValidation({})
        return
      }

      const response = await axios.post('/api/onboard/validate', payload)
      setValidation(response.data)

      const followUps: Promise<unknown>[] = []
      if (response.data?.gitlab?.ok && gitlab.baseGroup.trim()) {
        followUps.push(discoverGitLabGroups(true))
      }
      if (response.data?.jira?.ok) {
        followUps.push(discoverJiraProjects(true))
      }
      if (followUps.length > 0) {
        await Promise.all(followUps)
      }
    } catch (error: any) {
      setValidation({
        gitlab: codePlatform === 'gitlab' ? { ok: false, error: error.response?.data?.detail ?? 'Validation failed' } : null,
        github: codePlatform === 'github' ? { ok: false, error: error.response?.data?.detail ?? 'Validation failed' } : null,
      })
    } finally {
      setValidating(false)
    }
  }

  const updateTeam = (teamIndex: number, nextTeam: TeamForm) => {
    setTeams(current => current.map((team, index) => (index === teamIndex ? nextTeam : team)))
  }

  const addManualTeam = () => {
    setTeams(current => [
      ...current,
      {
        jiraKey: '',
        name: '',
        slug: '',
        scrumName: '',
        lead: '',
        leadEmail: '',
        gitlabPath: '',
        members: [],
      },
    ])
  }

  const buildTeamFromGroup = (group: GitLabGroup): TeamForm => {
    const derivedName = titleFromSlug(group.name || group.full_path.split('/').pop() || '')
    return {
      jiraKey: '',
      name: derivedName || group.name,
      slug: toSlug(group.name || group.full_path.split('/').pop() || ''),
      scrumName: derivedName || group.name,
      lead: '',
      leadEmail: '',
      gitlabPath: group.full_path,
      members: [],
    }
  }

  const addDiscoveredTeam = (group: GitLabGroup) => {
    setTeams(current => {
      if (current.some(team => team.gitlabPath === group.full_path)) {
        return current
      }
      return [...current, buildTeamFromGroup(group)]
    })
  }

  const addAllDiscoveredTeams = () => {
    setTeams(current => {
      const existing = new Set(current.map(team => team.gitlabPath))
      const freshTeams = discoveredGroups
        .filter(group => !existing.has(group.full_path))
        .map(buildTeamFromGroup)
      return [...current, ...freshTeams]
    })
  }

  const discoverMembersForTeam = async (teamIndex: number) => {
    const team = teams[teamIndex]
    const key = teamKey(team, teamIndex)
    if (!team?.gitlabPath) {
      setMemberErrors(current => ({ ...current, [key]: 'Add a GitLab path before discovering members.' }))
      return
    }

    setMemberLoading(current => ({ ...current, [key]: true }))
    setMemberErrors(current => {
      const next = { ...current }
      delete next[key]
      return next
    })

    try {
      const response = await axios.get('/api/onboard/discover/gitlab-members', {
        params: { group_path: team.gitlabPath, gitlab_url: gitlab.url.trim() },
        headers: {
          'X-GitLab-Token': gitlab.token,
          'X-GitLab-Url': gitlab.url.trim(),
        },
      })

      const discoveredMembers: Member[] = (response.data.members ?? []).map((member: any) => ({
        username: member.username || '',
        name: member.name || member.username || '',
        email: '',
        role: normaliseRole(member.role),
      }))

      updateTeam(teamIndex, { ...team, members: discoveredMembers })
    } catch (error: any) {
      setMemberErrors(current => ({
        ...current,
        [key]: error.response?.data?.detail ?? 'Member discovery failed',
      }))
    } finally {
      setMemberLoading(current => ({ ...current, [key]: false }))
    }
  }

  const discoverMembersForAll = async () => {
    if (teams.length === 0) return

    setBulkDiscoveringMembers(true)
    const results = await Promise.allSettled(
      teams.map(async (team, index) => {
        if (!team.gitlabPath) {
          throw new Error(`${team.name || `Team ${index + 1}`} is missing a GitLab path`)
        }
        const response = await axios.get('/api/onboard/discover/gitlab-members', {
          params: { group_path: team.gitlabPath, gitlab_url: gitlab.url.trim() },
          headers: {
            'X-GitLab-Token': gitlab.token,
            'X-GitLab-Url': gitlab.url.trim(),
          },
        })
        return {
          index,
          members: (response.data.members ?? []).map((member: any) => ({
            username: member.username || '',
            name: member.name || member.username || '',
            email: '',
            role: normaliseRole(member.role),
          })) as Member[],
        }
      }),
    )

    setTeams(current =>
      current.map((team, index) => {
        const match = results.find(result => result.status === 'fulfilled' && result.value.index === index)
        if (!match || match.status !== 'fulfilled') return team
        return { ...team, members: match.value.members }
      }),
    )

    const nextErrors: Record<string, string> = {}
    results.forEach((result, index) => {
      if (result.status === 'rejected') {
        nextErrors[teamKey(teams[index], index)] = result.reason?.message || 'Member discovery failed'
      }
    })
    setMemberErrors(current => ({ ...current, ...nextErrors }))
    setBulkDiscoveringMembers(false)
  }

  const pollSyncProgress = async () => {
    try {
      const response = await axios.get('/api/sync/schedule')
      setSyncInfo(response.data)
      const engineerStatus = response.data?.sections?.engineers?.status
      if (engineerStatus === 'success' || engineerStatus === 'error') {
        setSyncReady(true)
        window.setTimeout(() => onComplete(), 900)
        return true
      }
    } catch {
      // Backend may still be warming up.
    }
    return false
  }

  const createDomain = async () => {
    setCreating(true)
    setCreateError(null)
    try {
      const payload: Record<string, unknown> = {
        organization: {
          name: org.name.trim(),
          slug: org.slug.trim(),
          description: org.description.trim(),
        },
        user: {
          name: user.name.trim(),
          email: user.email.trim(),
          role: user.role.trim(),
          timezone: user.timezone.trim(),
        },
        teams: teams.map(team => ({
          key: team.jiraKey.trim() || team.slug.toUpperCase().replace(/-/g, '_'),
          name: team.name.trim(),
          slug: team.slug.trim(),
          scrum_name: team.scrumName.trim() || team.name.trim(),
          lead: team.lead.trim(),
          lead_email: team.leadEmail.trim(),
          headcount: team.members.length,
          jira_project: team.jiraKey.trim() || undefined,
          gitlab_path: team.gitlabPath.trim(),
          gitlab_members: team.members.map(member => ({
            username: member.username.trim(),
            name: member.name.trim(),
            role: member.role,
            email: member.email.trim() || undefined,
          })),
        })),
      }

      // Code platform
      if (codePlatform === 'gitlab' && gitlab.token.trim()) {
        payload.gitlab = { token: gitlab.token, url: gitlab.url.trim(), base_group: gitlab.baseGroup.trim() }
      }
      if (codePlatform === 'github' && github.token.trim()) {
        payload.github = { token: github.token, org: github.org.trim() }
      }

      // Issue tracker
      if (issueTracker === 'jira' && jira.url.trim() && jira.email.trim() && jira.token.trim()) {
        payload.jira = { url: jira.url.trim(), email: jira.email.trim(), token: jira.token }
      }
      if (issueTracker === 'linear' && linear.apiKey.trim()) {
        payload.linear = { api_key: linear.apiKey }
      }
      if (issueTracker === 'monday' && monday.token.trim()) {
        payload.monday = { token: monday.token }
      }
      if (issueTracker === 'asana' && asana.token.trim()) {
        payload.asana = { token: asana.token }
      }

      // AI
      if (aiProvider !== 'none') {
        payload.llm = {
          openai_api_key: aiProvider === 'openai' ? ai.openaiKey.trim() : '',
          anthropic_api_key: aiProvider === 'anthropic' ? ai.anthropicKey.trim() : '',
        }
      }

      // Port + Snyk (keep existing pattern)
      if (optional.portClientId.trim() || optional.portClientSecret.trim() || optional.snykToken.trim()) {
        payload.optional = {
          port_client_id: optional.portClientId.trim(),
          port_client_secret: optional.portClientSecret.trim(),
          port_base_url: optional.portBaseUrl.trim(),
          snyk_token: optional.snykToken.trim(),
        }
      }

      await axios.post('/api/onboard/create', payload)
      setStep('syncing')
      const initialDone = await pollSyncProgress()
      if (initialDone) {
        return
      }
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise(resolve => window.setTimeout(resolve, 3000))
        const done = await pollSyncProgress()
        if (done) return
      }
      onComplete()
    } catch (error: any) {
      setCreateError(error.response?.data?.detail ?? 'Failed to create the domain')
    } finally {
      setCreating(false)
    }
  }

  const nextStep = () => {
    if (step === 'basics') setStep('connections')
    if (step === 'connections') setStep('teams')
    if (step === 'teams') setStep('review')
    if (step === 'review') void createDomain()
  }

  const previousStep = () => {
    if (step === 'review') setStep('teams')
    if (step === 'teams') setStep('connections')
    if (step === 'connections') setStep('basics')
  }

  const renderStepContent = () => {
    if (step === 'syncing') {
      return (
        <div className="rounded-[2rem] border border-slate-800 bg-slate-900/85 p-8 shadow-[0_24px_80px_rgba(2,12,27,0.45)] backdrop-blur">
          <div className="mx-auto max-w-2xl text-center">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl border border-cyan-500/30 bg-cyan-500/10 text-cyan-300">
              {syncReady ? <CheckCircle2 size={28} /> : <Loader2 size={28} className="animate-spin" />}
            </div>
            <h2 className="mt-6 text-2xl font-semibold text-white">
              {syncReady ? 'Initial sync complete' : 'Creating the domain and pulling live data'}
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-400">
              {syncReady
                ? 'The dashboard is ready. Opening it now.'
                : 'GitLab, Jira, and metrics sync are running against the new domain. This page updates from the scheduler instead of guessing.'}
            </p>
          </div>

          <div className="mt-8 grid gap-3 md:grid-cols-3">
            <SyncStatusCard section="Engineers" status={syncInfo?.sections?.engineers} />
            <SyncStatusCard section="Team metrics" status={syncInfo?.sections?.team_metrics} />
            <SyncStatusCard section="Jira epics" status={syncInfo?.sections?.jira_epics} />
          </div>

          <div className="mt-6 flex justify-center">
            <button
              type="button"
              onClick={onComplete}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
            >
              Open dashboard now
              <ArrowRight size={14} />
            </button>
          </div>
        </div>
      )
    }

    return (
      <div className="rounded-[2rem] border border-slate-800 bg-slate-900/85 p-6 shadow-[0_24px_80px_rgba(2,12,27,0.45)] backdrop-blur md:p-8">
        {step === 'basics' ? (
          <div>
            <div className="mb-8 flex items-start gap-4">
              <div className="rounded-3xl bg-cyan-500/10 p-3 text-cyan-300">
                <Building2 size={22} />
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Domain identity</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">Set the domain up once, then let the app do the rest.</h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                  This onboarding creates an isolated domain config, stores runtime credentials locally for that domain, seeds its database, and immediately starts syncing data.
                </p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Domain name</span>
                <input
                  className="setup-input"
                  value={org.name}
                  placeholder="Acme Engineering"
                  autoFocus
                  onChange={event =>
                    setOrg(current => ({
                      ...current,
                      name: event.target.value,
                      slug: lockedSlug ? current.slug : current.slug || toSlug(event.target.value),
                    }))
                  }
                />
              </label>
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Slug</span>
                <input
                  className="setup-input font-mono"
                  value={org.slug}
                  disabled={lockedSlug}
                  placeholder="acme-eng"
                  onChange={event => setOrg(current => ({ ...current, slug: toSlug(event.target.value) }))}
                />
              </label>
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Owner role</span>
                <input
                  className="setup-input"
                  value={user.role}
                  placeholder="Engineering Manager"
                  onChange={event => setUser(current => ({ ...current, role: event.target.value }))}
                />
              </label>
              <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Description</span>
                <textarea
                  className="setup-input min-h-[120px] resize-y"
                  value={org.description}
                  placeholder="What this domain owns, why it exists, and what teams it includes."
                  onChange={event => setOrg(current => ({ ...current, description: event.target.value }))}
                />
              </label>
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Owner name</span>
                <input
                  className="setup-input"
                  value={user.name}
                  placeholder="Your name"
                  onChange={event => setUser(current => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label className="space-y-2 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Owner email</span>
                <input
                  className="setup-input"
                  value={user.email}
                  placeholder="you@company.com"
                  onChange={event => setUser(current => ({ ...current, email: event.target.value }))}
                />
              </label>
            </div>
          </div>
        ) : null}

        {step === 'connections' ? (
          <div>
            <div className="mb-8 flex items-start gap-4">
              <div className="rounded-3xl bg-cyan-500/10 p-3 text-cyan-300">
                <KeyRound size={22} />
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Runtime credentials</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">Connect the tools your org uses.</h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                  Every integration is optional. Pick the code platform, issue tracker, AI provider, and security scanner that match your stack. Validate before moving on.
                </p>
              </div>
            </div>

            <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
              <div className="space-y-6">
                {/* Code Platform */}
                <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <FolderGit2 className="text-cyan-300" size={18} />
                      <div>
                        <p className="text-sm font-semibold text-white">Code platform</p>
                        <p className="text-xs text-slate-500">Engineer activity, MR metrics, and repo discovery.</p>
                      </div>
                    </div>
                    <select
                      className="setup-input !w-auto !py-2 !px-3 !text-xs"
                      value={codePlatform}
                      onChange={event => setCodePlatform(event.target.value as CodePlatform)}
                    >
                      <option value="none">None</option>
                      <option value="gitlab">GitLab</option>
                      <option value="github">GitHub</option>
                    </select>
                  </div>

                  {codePlatform === 'gitlab' ? (
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                      <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Base URL</span>
                        <input
                          className="setup-input"
                          value={gitlab.url}
                          placeholder="https://gitlab.com"
                          onChange={event => setGitlab(current => ({ ...current, url: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Personal access token</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={gitlab.token}
                          placeholder="glpat-..."
                          onChange={event => setGitlab(current => ({ ...current, token: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Base group for discovery</span>
                        <input
                          className="setup-input font-mono text-xs"
                          value={gitlab.baseGroup}
                          placeholder="acme/teams"
                          onChange={event => setGitlab(current => ({ ...current, baseGroup: event.target.value }))}
                        />
                      </label>
                    </div>
                  ) : null}

                  {codePlatform === 'github' ? (
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                      <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Personal access token</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={github.token}
                          placeholder="ghp_..."
                          onChange={event => setGithub(current => ({ ...current, token: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Organization (optional)</span>
                        <input
                          className="setup-input font-mono text-xs"
                          value={github.org}
                          placeholder="my-org"
                          onChange={event => setGithub(current => ({ ...current, org: event.target.value }))}
                        />
                      </label>
                    </div>
                  ) : null}
                </div>

                {/* Issue Tracker */}
                <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <ShieldCheck className="text-amber-300" size={18} />
                      <div>
                        <p className="text-sm font-semibold text-white">Issue tracker</p>
                        <p className="text-xs text-slate-500">Epic health, roadmap views, and project drill-through.</p>
                      </div>
                    </div>
                    <select
                      className="setup-input !w-auto !py-2 !px-3 !text-xs"
                      value={issueTracker}
                      onChange={event => setIssueTracker(event.target.value as IssueTracker)}
                    >
                      <option value="none">None</option>
                      <option value="jira">Jira</option>
                      <option value="linear">Linear</option>
                      <option value="monday">Monday.com</option>
                      <option value="asana">Asana</option>
                    </select>
                  </div>

                  {issueTracker === 'jira' ? (
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                      <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Jira URL</span>
                        <input
                          className="setup-input"
                          value={jira.url}
                          placeholder="https://your-org.atlassian.net"
                          onChange={event => setJira(current => ({ ...current, url: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Email</span>
                        <input
                          className="setup-input"
                          value={jira.email}
                          placeholder="you@company.com"
                          onChange={event => setJira(current => ({ ...current, email: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API token</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={jira.token}
                          placeholder="ATATT3x..."
                          onChange={event => setJira(current => ({ ...current, token: event.target.value }))}
                        />
                      </label>
                    </div>
                  ) : null}

                  {issueTracker === 'linear' ? (
                    <div className="mt-5">
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API key</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={linear.apiKey}
                          placeholder="lin_api_..."
                          onChange={event => setLinear({ apiKey: event.target.value })}
                        />
                      </label>
                    </div>
                  ) : null}

                  {issueTracker === 'monday' ? (
                    <div className="mt-5">
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">API token</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={monday.token}
                          placeholder="Monday API token"
                          onChange={event => setMonday({ token: event.target.value })}
                        />
                      </label>
                    </div>
                  ) : null}

                  {issueTracker === 'asana' ? (
                    <div className="mt-5">
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Personal access token</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={asana.token}
                          placeholder="Asana PAT"
                          onChange={event => setAsana({ token: event.target.value })}
                        />
                      </label>
                    </div>
                  ) : null}
                </div>

                {/* AI Provider */}
                <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <Sparkles className="text-violet-300" size={18} />
                      <div>
                        <p className="text-sm font-semibold text-white">AI provider</p>
                        <p className="text-xs text-slate-500">Powers AI summaries and analysis features.</p>
                      </div>
                    </div>
                    <select
                      className="setup-input !w-auto !py-2 !px-3 !text-xs"
                      value={aiProvider}
                      onChange={event => setAiProvider(event.target.value as AiProvider)}
                    >
                      <option value="none">None</option>
                      <option value="openai">OpenAI</option>
                      <option value="anthropic">Anthropic</option>
                    </select>
                  </div>

                  {aiProvider === 'openai' ? (
                    <div className="mt-5">
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">OpenAI API key</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={ai.openaiKey}
                          placeholder="sk-..."
                          onChange={event => setAi(current => ({ ...current, openaiKey: event.target.value }))}
                        />
                      </label>
                    </div>
                  ) : null}

                  {aiProvider === 'anthropic' ? (
                    <div className="mt-5">
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Anthropic API key</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={ai.anthropicKey}
                          placeholder="sk-ant-..."
                          onChange={event => setAi(current => ({ ...current, anthropicKey: event.target.value }))}
                        />
                      </label>
                    </div>
                  ) : null}
                </div>

                {/* Security */}
                <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <ShieldCheck className="text-emerald-300" size={18} />
                      <div>
                        <p className="text-sm font-semibold text-white">Security</p>
                        <p className="text-xs text-slate-500">Vulnerability scanning and security views.</p>
                      </div>
                    </div>
                    <select
                      className="setup-input !w-auto !py-2 !px-3 !text-xs"
                      value={securityProvider}
                      onChange={event => setSecurityProvider(event.target.value as SecurityProvider)}
                    >
                      <option value="none">None</option>
                      <option value="snyk">Snyk</option>
                    </select>
                  </div>

                  {securityProvider === 'snyk' ? (
                    <div className="mt-5">
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Snyk token</span>
                        <input
                          className="setup-input font-mono text-xs"
                          type="password"
                          value={optional.snykToken}
                          placeholder="Snyk API token"
                          onChange={event => setOptional(current => ({ ...current, snykToken: event.target.value }))}
                        />
                      </label>
                    </div>
                  ) : null}
                </div>

                {/* Port (advanced, collapsible) */}
                <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                  <button
                    type="button"
                    onClick={() => setAdvancedOpen(open => !open)}
                    className="flex w-full items-center justify-between gap-3 text-left"
                  >
                    <div>
                      <p className="text-sm font-semibold text-white">Port (advanced)</p>
                      <p className="mt-1 text-xs text-slate-500">Service catalog and Port-backed DORA metrics.</p>
                    </div>
                    <ChevronRight size={16} className={`text-slate-500 transition-transform ${advancedOpen ? 'rotate-90' : ''}`} />
                  </button>

                  {advancedOpen ? (
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Port client ID</span>
                        <input
                          className="setup-input"
                          value={optional.portClientId}
                          onChange={event => setOptional(current => ({ ...current, portClientId: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2 text-sm text-slate-300">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Port client secret</span>
                        <input
                          className="setup-input"
                          type="password"
                          value={optional.portClientSecret}
                          onChange={event => setOptional(current => ({ ...current, portClientSecret: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2 text-sm text-slate-300 md:col-span-2">
                        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Port base URL</span>
                        <input
                          className="setup-input"
                          value={optional.portBaseUrl}
                          onChange={event => setOptional(current => ({ ...current, portBaseUrl: event.target.value }))}
                        />
                      </label>
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="space-y-4">
                {codePlatform === 'gitlab' ? <ValidationBadge label="GitLab" result={validation?.gitlab} /> : null}
                {codePlatform === 'github' ? <ValidationBadge label="GitHub" result={validation?.github} /> : null}
                {issueTracker === 'jira' ? <ValidationBadge label="Jira" result={validation?.jira} /> : null}
                {issueTracker === 'linear' ? <ValidationBadge label="Linear" result={validation?.linear} /> : null}
                {issueTracker === 'monday' ? <ValidationBadge label="Monday" result={validation?.monday} /> : null}
                {issueTracker === 'asana' ? <ValidationBadge label="Asana" result={validation?.asana} /> : null}
                {aiProvider === 'openai' ? <ValidationBadge label="OpenAI" result={validation?.openai} /> : null}
                {aiProvider === 'anthropic' ? <ValidationBadge label="Anthropic" result={validation?.anthropic} /> : null}
                {securityProvider === 'snyk' ? <ValidationBadge label="Snyk" result={validation?.snyk} /> : null}

                {!hasAnyConnection ? (
                  <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs leading-5 text-amber-200">
                    No integrations selected. Pick at least one provider to validate, or skip ahead.
                  </div>
                ) : null}

                <button
                  type="button"
                  onClick={validateConnections}
                  disabled={validating || !hasAnyConnection}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-cyan-400 px-4 py-3 text-sm font-semibold text-slate-950 transition-colors hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                >
                  {validating ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
                  Validate connections
                </button>

                {codePlatform === 'gitlab' && validation?.gitlab?.ok && gitlab.baseGroup.trim() ? (
                  <button
                    type="button"
                    onClick={() => void discoverGitLabGroups(false)}
                    disabled={discoveringGroups}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-700 px-4 py-3 text-sm font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {discoveringGroups ? <Loader2 size={16} className="animate-spin" /> : <FolderGit2 size={16} />}
                    Discover GitLab teams
                  </button>
                ) : null}

                {issueTracker === 'jira' && validation?.jira?.ok ? (
                  <button
                    type="button"
                    onClick={() => void discoverJiraProjects(false)}
                    disabled={discoveringProjects}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-700 px-4 py-3 text-sm font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {discoveringProjects ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
                    Discover Jira projects
                  </button>
                ) : null}

                {groupsError ? (
                  <div className="rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-xs leading-5 text-rose-200">
                    {groupsError}
                  </div>
                ) : null}
                {projectsError ? (
                  <div className="rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-xs leading-5 text-rose-200">
                    {projectsError}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}

        {step === 'teams' ? (
          <div>
            <div className="mb-8 flex items-start gap-4">
              <div className="rounded-3xl bg-cyan-500/10 p-3 text-cyan-300">
                <Users size={22} />
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Team discovery</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">Turn GitLab structure into configured teams.</h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                  Select discovered groups, map Jira projects if you have them, then pull inherited members from GitLab. This is the step that makes the rest of the app useful.
                </p>
              </div>
            </div>

            <div className="mb-6 grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
              <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-semibold text-white">Discovered GitLab groups</p>
                    <p className="mt-1 text-xs text-slate-500">Select subgroups under the configured base group, or add teams manually.</p>
                  </div>
                  {discoveredGroups.length > 0 ? (
                    <button
                      type="button"
                      onClick={addAllDiscoveredTeams}
                      className="inline-flex items-center gap-2 rounded-2xl border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-medium text-cyan-200 transition-colors hover:border-cyan-400/60 hover:bg-cyan-500/15"
                    >
                      <Plus size={12} />
                      Add all
                    </button>
                  ) : null}
                </div>

                <label className="mt-4 flex items-center gap-2 rounded-2xl border border-slate-800 bg-slate-900/70 px-3 py-2 text-sm text-slate-400">
                  <Search size={14} />
                  <input
                    value={groupSearch}
                    onChange={event => setGroupSearch(event.target.value)}
                    placeholder="Filter by group name or path"
                    className="w-full bg-transparent text-sm text-white outline-none placeholder:text-slate-600"
                  />
                </label>

                <div className="mt-4 space-y-3 max-h-[520px] overflow-auto pr-1">
                  {filteredGroups.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-slate-800 px-4 py-8 text-sm text-slate-500">
                      {discoveredGroups.length === 0
                        ? 'No GitLab groups discovered yet. Validate connections, then discover teams from the base group.'
                        : 'No groups match the current filter.'}
                    </div>
                  ) : (
                    filteredGroups.map(group => {
                      const alreadyAdded = teams.some(team => team.gitlabPath === group.full_path)
                      return (
                        <div key={group.id} className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
                          <div className="flex items-start justify-between gap-4">
                            <div>
                              <p className="text-sm font-semibold text-white">{titleFromSlug(group.name) || group.name}</p>
                              <p className="mt-1 font-mono text-[11px] text-slate-500">{group.full_path}</p>
                              {group.description ? <p className="mt-2 text-xs leading-5 text-slate-400">{group.description}</p> : null}
                            </div>
                            <button
                              type="button"
                              onClick={() => addDiscoveredTeam(group)}
                              disabled={alreadyAdded}
                              className="inline-flex shrink-0 items-center gap-2 rounded-2xl border border-slate-700 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:border-emerald-500/30 disabled:bg-emerald-500/10 disabled:text-emerald-200"
                            >
                              {alreadyAdded ? <Check size={12} /> : <Plus size={12} />}
                              {alreadyAdded ? 'Added' : 'Add'}
                            </button>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>

              <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-white">Configured teams</p>
                    <p className="mt-1 text-xs text-slate-500">Every team needs a name, slug, and GitLab path before the wizard can create the domain.</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void discoverMembersForAll()}
                      disabled={bulkDiscoveringMembers || teams.length === 0}
                      className="inline-flex items-center gap-2 rounded-2xl border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-medium text-cyan-200 transition-colors hover:border-cyan-400/60 hover:bg-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {bulkDiscoveringMembers ? <Loader2 size={12} className="animate-spin" /> : <RefreshCcw size={12} />}
                      Discover members for all
                    </button>
                    <button
                      type="button"
                      onClick={addManualTeam}
                      className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
                    >
                      <Plus size={12} />
                      Add manual team
                    </button>
                  </div>
                </div>

                {teams.length === 0 ? (
                  <div className="mt-5 rounded-2xl border border-dashed border-slate-800 px-4 py-8 text-sm text-slate-500">
                    No teams added yet. Use the discovered groups on the left or add a team manually.
                  </div>
                ) : (
                  <div className="mt-5 space-y-4 max-h-[520px] overflow-auto pr-1">
                    {teams.map((team, index) => {
                      const key = teamKey(team, index)
                      return (
                        <TeamEditor
                          key={key}
                          team={team}
                          index={index}
                          projectOptions={discoveredProjects}
                          onChange={nextTeam => updateTeam(index, nextTeam)}
                          onRemove={() => setTeams(current => current.filter((_, teamIndex) => teamIndex !== index))}
                          onDiscoverMembers={() => void discoverMembersForTeam(index)}
                          discoveringMembers={Boolean(memberLoading[key])}
                          memberError={memberErrors[key]}
                        />
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {step === 'review' ? (
          <div>
            <div className="mb-8 flex items-start gap-4">
              <div className="rounded-3xl bg-cyan-500/10 p-3 text-cyan-300">
                <Rocket size={22} />
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Review and create</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">Create the domain with enough context to be useful immediately.</h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                  Credentials will be stored locally in a domain-scoped secrets file, not exposed through the config API. After create, the app seeds the new domain and starts the initial sync.
                </p>
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Domain</p>
                    <p className="mt-2 text-lg font-semibold text-white">{org.name}</p>
                    <p className="mt-1 font-mono text-xs text-cyan-300">{org.slug}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Teams</p>
                    <p className="mt-2 text-lg font-semibold text-white">{teams.length}</p>
                    <p className="mt-1 text-xs text-slate-500">{teamsWithoutMembers.length} without members</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Code platform</p>
                    <p className="mt-2 text-sm text-white">
                      {codePlatform === 'gitlab' ? `GitLab — ${validation?.gitlab?.user || 'Validated'}` :
                       codePlatform === 'github' ? `GitHub — ${validation?.github?.user || 'Validated'}` :
                       'None'}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Issue tracker</p>
                    <p className="mt-2 text-sm text-white">
                      {issueTracker === 'jira' ? `Jira — ${validation?.jira?.user || 'Validated'}` :
                       issueTracker === 'linear' ? `Linear — ${validation?.linear?.user || 'Validated'}` :
                       issueTracker === 'monday' ? `Monday — ${validation?.monday?.user || 'Validated'}` :
                       issueTracker === 'asana' ? `Asana — ${validation?.asana?.user || 'Validated'}` :
                       'None'}
                    </p>
                  </div>
                </div>

                <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Team summary</p>
                  <div className="mt-3 space-y-3">
                    {teams.map(team => (
                      <div key={team.slug} className="flex items-start justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                        <div>
                          <p className="text-sm font-medium text-white">{team.name}</p>
                          <p className="mt-1 font-mono text-[11px] text-slate-500">{team.gitlabPath}</p>
                        </div>
                        <div className="text-right text-xs text-slate-400">
                          <p>{team.jiraKey || 'No Jira link'}</p>
                          <p className="mt-1">{team.members.length} members</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-3xl border border-amber-500/20 bg-amber-500/8 p-5">
                  <p className="text-sm font-semibold text-white">Readiness check</p>
                  <div className="mt-4 space-y-3">
                    {reviewWarnings.map(warning => (
                      <div key={warning} className="flex items-start gap-2 text-sm leading-6 text-amber-100">
                        <AlertCircle size={15} className="mt-1 shrink-0 text-amber-300" />
                        <span>{warning}</span>
                      </div>
                    ))}
                    {reviewWarnings.length === 0 ? (
                      <div className="flex items-start gap-2 text-sm leading-6 text-emerald-200">
                        <CheckCircle2 size={15} className="mt-1 shrink-0 text-emerald-300" />
                        <span>The onboarding payload is complete. Creating the domain should lead straight into a useful dashboard.</span>
                      </div>
                    ) : null}
                  </div>
                </div>

                {createError ? (
                  <div className="rounded-3xl border border-rose-500/25 bg-rose-500/10 p-5 text-sm text-rose-200">
                    {createError}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.12),transparent_32%),radial-gradient(circle_at_top_right,rgba(251,191,36,0.08),transparent_24%),linear-gradient(180deg,#020617_0%,#020617_46%,#050b17_100%)] px-4 py-6 text-white md:px-6 lg:px-8">
      <div className="mx-auto max-w-[1440px]">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.28em] text-cyan-300/80">Engineering dashboard</p>
            <h1 className="mt-2 text-3xl font-semibold text-white md:text-4xl">
              {isNewDomain ? 'Onboard a new domain' : 'Complete onboarding for this domain'}
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400 md:text-base">
              The goal here is not just to create a config file. It is to finish with a domain that can immediately sync activity from your code platform and issue tracker, and open into a dashboard that already makes sense.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/85 px-4 py-3 text-xs text-slate-400 shadow-[0_14px_40px_rgba(2,12,27,0.35)]">
            Active path: <span className="font-mono text-cyan-300">{step === 'syncing' ? 'syncing' : `${currentStepIndex + 1}/${STEPS.length}`}</span>
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          {step === 'syncing' ? (
            <div className="xl:col-span-2">{renderStepContent()}</div>
          ) : (
            <>
              <div className="space-y-4">
                <StepRail current={step} onSelect={setStep} />
                <div className="rounded-3xl border border-slate-800 bg-slate-900/85 p-5 shadow-[0_24px_80px_rgba(2,12,27,0.45)] backdrop-blur">
                  <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">What this fixes</p>
                  <ul className="mt-4 space-y-3 text-sm leading-6 text-slate-300">
                    <li>Credentials are validated before create and stored per domain instead of relying on machine-wide env vars.</li>
                    <li>GitLab discovery supports custom GitLab URLs, not just gitlab.com.</li>
                    <li>Inherited group members are discoverable, so teams start with real people instead of empty shells.</li>
                    <li>Post-create sync shows real section status from the scheduler instead of a blind spinner.</li>
                  </ul>
                </div>
              </div>

              <div>
                {renderStepContent()}

                <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={previousStep}
                    disabled={step === 'basics' || creating}
                    className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 px-4 py-3 text-sm font-medium text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <ChevronLeft size={16} />
                    Back
                  </button>

                  <div className="flex items-center gap-3">
                    {readinessHint ? <p className="max-w-xl text-xs text-slate-500">{readinessHint}</p> : null}
                    <button
                      type="button"
                      onClick={nextStep}
                      disabled={creating}
                      className="inline-flex items-center gap-2 rounded-2xl bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition-colors hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                    >
                      {creating ? <Loader2 size={16} className="animate-spin" /> : null}
                      {step === 'review' ? 'Create domain' : 'Continue'}
                      {!creating ? <ChevronRight size={16} /> : null}
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <style>{`
        .setup-input {
          width: 100%;
          border-radius: 1rem;
          border: 1px solid rgba(51, 65, 85, 0.9);
          background: rgba(15, 23, 42, 0.88);
          color: white;
          padding: 0.875rem 1rem;
          font-size: 0.95rem;
          line-height: 1.4;
          outline: none;
          transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
        }
        .setup-input::placeholder {
          color: rgb(100 116 139);
        }
        .setup-input:focus {
          border-color: rgba(34, 211, 238, 0.7);
          box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.12);
          background: rgba(15, 23, 42, 0.96);
        }
        .setup-input:disabled {
          cursor: not-allowed;
          opacity: 0.75;
        }
      `}</style>
    </div>
  )
}
