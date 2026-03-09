import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTeamMetrics, getConfig, getJiraEpics, getSectionSyncStatus, triggerSync, syncJira, getSyncSchedule, getTeamSummaryWithCompare, getTeamTrend } from '../api/client'
import type { OrgConfig, TeamConfig, JiraEpic } from '../api/client'
import TeamHealthCard from '../components/TeamHealthCard'
import LoadingSpinner from '../components/LoadingSpinner'
import PeriodSelector, { type PeriodDays } from '../components/PeriodSelector'
import SyncStatusBadge from '../components/SyncStatusBadge'
import { downloadCsv } from '../utils/export'

// Shape returned by /api/gitlab/metrics
interface RawTeamMetric {
  name: string
  level: string
  totalMRs: number
  deployFreq: number
  leadTime: number
  failureRate: number
}

// Shape used inside this component
interface TeamMetric {
  team: string
  display: string
  engineer_count: number
  active_mrs: number
  dora_level: string
  deploy_freq: number
  warnings: string[]
  jira_project: string | undefined
}

function buildCards(
  config: OrgConfig,
  rawMetrics: RawTeamMetric[],
  teamMrCounts: Record<string, number>,
): TeamMetric[] {
  const bySlug = new Map<string, RawTeamMetric>()
  for (const m of rawMetrics) {
    bySlug.set(m.name, m)
  }

  return config.teams.map((t: TeamConfig) => {
    const slug = t.slug ?? t.key.toLowerCase()
    const metric = bySlug.get(slug) ?? bySlug.get(t.key.toLowerCase())
    const warnings: string[] = []
    if (metric && metric.deployFreq < 5) warnings.push('Low deploy frequency')
    if (metric && metric.failureRate > 20) warnings.push('High failure rate')
    return {
      team: slug,
      display: t.scrum_name ? `${t.name} (${t.scrum_name})` : t.name,
      engineer_count: t.headcount,
      // Use period-aware MR count from ecosystem.db, fall back to DORA metrics
      active_mrs: teamMrCounts[slug] ?? metric?.totalMRs ?? 0,
      dora_level: metric ? capitalize(metric.level) : 'Unknown',
      deploy_freq: metric?.deployFreq ?? 0,
      warnings,
      jira_project: t.jira_project,
    }
  })
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export default function Dashboard() {
  const [cards, setCards] = useState<TeamMetric[]>([])
  const [config, setConfig] = useState<OrgConfig | null>(null)
  const [epicsByProject, setEpicsByProject] = useState<Record<string, JiraEpic[]>>({})
  const [deltas, setDeltas] = useState<Record<string, { current: number; previous: number; delta: number; pct_change: number | null }>>({})
  const [sparklines, setSparklines] = useState<Record<string, number[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState<PeriodDays>(30)
  const [syncInfo, setSyncInfo] = useState<any>(null)
  const [syncing, setSyncing] = useState(false)
  const [jiraSyncing, setJiraSyncing] = useState(false)
  const [schedulerRunning, setSchedulerRunning] = useState(false)
  const [schedulerPaused, setSchedulerPaused] = useState(false)
  const navigate = useNavigate()

  const fetchData = () => {
    setLoading(true)
    setError(null)
    Promise.all([
      getConfig(),
      getTeamMetrics(days),
      getTeamSummaryWithCompare(days),
      getJiraEpics(undefined, 'In Progress'),
      getSectionSyncStatus('engineers', days),
    ])
      .then(async ([configRes, metricsRes, summaryRes, epicsRes, syncRes]) => {
        // Fetch scheduler state (non-blocking)
        getSyncSchedule().then(schedRes => {
          setSchedulerRunning(schedRes.data.scheduler.running)
          setSchedulerPaused(schedRes.data.scheduler.paused)
        }).catch(() => {}) // Scheduler info is optional

        // Store deltas from compare response
        if (summaryRes.data.deltas) {
          setDeltas(summaryRes.data.deltas)
        }
        const cfg = configRes.data
        setConfig(cfg)
        const raw = metricsRes.data as { teams?: RawTeamMetric[] }
        const mrCounts = summaryRes.data.teams ?? {}
        const builtCards = buildCards(cfg, raw.teams ?? [], mrCounts)
        setCards(builtCards)

        // Fetch sparkline data for each team (non-blocking)
        const teamSlugs = builtCards.map(c => c.team)
        Promise.all(
          teamSlugs.map(slug =>
            getTeamTrend(slug, Math.max(days, 90))
              .then(r => ({ slug, data: r.data.buckets.map((b: { mrs: number }) => b.mrs) }))
              .catch(() => ({ slug, data: [] as number[] }))
          )
        ).then(results => {
          const sparkMap: Record<string, number[]> = {}
          for (const { slug, data } of results) sparkMap[slug] = data
          setSparklines(sparkMap)
        })
        // Group in-progress epics by Jira project key (e.g. "MA", "NS")
        const byProject: Record<string, JiraEpic[]> = {}
        for (const epic of epicsRes.data.epics) {
          if (!byProject[epic.project]) byProject[epic.project] = []
          byProject[epic.project].push(epic)
        }
        setEpicsByProject(byProject)
        setSyncInfo(syncRes.data)

      })
      .catch(err => setError(err?.message ?? 'Failed to load data'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchData()
  }, [days])

  const handleRefresh = async (force_full = false) => {
    setSyncing(true)
    try {
      await triggerSync('engineers', days, force_full)
      await new Promise(r => setTimeout(r, 2000))
      fetchData()
    } finally {
      setSyncing(false)
    }
  }

  const handleJiraSync = async () => {
    setJiraSyncing(true)
    try {
      await syncJira()
      await new Promise(r => setTimeout(r, 3000))
      fetchData()
    } finally {
      setJiraSyncing(false)
    }
  }

  const totalEngineers = cards.reduce((sum, t) => sum + t.engineer_count, 0)
  const handleExport = () => {
    downloadCsv(`dashboard-${days}d.csv`, cards.map(team => ({
      team: team.display,
      slug: team.team,
      engineers: team.engineer_count,
      active_mrs: team.active_mrs,
      dora_level: team.dora_level,
      deploy_frequency: team.deploy_freq,
      warnings: team.warnings.join(' | '),
      in_progress_epics: (epicsByProject[team.jira_project ?? ''] ?? []).length,
    })))
  }

  if (loading) return <LoadingSpinner text="Loading dashboard..." />

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
          {error}
        </div>
      </div>
    )
  }

  const isUnconfigured = config !== null && config.teams.length === 0
  if (isUnconfigured) {
    const slug = config.organization?.slug ?? ''
    const params = new URLSearchParams({
      slug,
      name: config.organization?.name ?? '',
    })
    const setupUrl = `/setup?${params.toString()}`
    return (
      <div className="p-6">
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-6">
          <div className="flex items-start gap-4">
            <span className="text-yellow-400 text-2xl">⚠</span>
            <div>
              <h2 className="text-white font-semibold text-base mb-1">
                This domain isn't configured yet
              </h2>
              <p className="text-gray-400 text-sm mb-4">
                Add your code platform and issue tracker credentials to start tracking{' '}
                <span className="text-white">{config.organization?.name}</span> teams.
              </p>
              <a
                href={setupUrl}
                className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                Complete Setup →
              </a>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">
            {config?.organization?.name ?? 'Engineering'} Dashboard
          </h2>
          <p className="text-gray-400 text-sm mt-1">Team health overview — last {days >= 365 ? '12 months' : `${days} days`}</p>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={handleExport}
            className="text-xs text-gray-300 hover:text-white border border-gray-700 hover:border-gray-500 rounded-lg px-3 py-2 transition-colors whitespace-nowrap"
          >
            Export CSV
          </button>
          <SyncStatusBadge syncInfo={syncInfo} onRefresh={handleRefresh} loading={syncing} schedulerRunning={schedulerRunning} schedulerPaused={schedulerPaused} />
          <button
            onClick={handleJiraSync}
            disabled={jiraSyncing}
            className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40 transition-colors whitespace-nowrap"
          >
            {jiraSyncing ? 'Syncing Jira…' : '↻ Sync Jira'}
          </button>
          <PeriodSelector value={days} onChange={setDays} />
          <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-center">
            <p className="text-2xl font-bold text-white">{cards.length}</p>
            <p className="text-xs text-gray-400">Teams</p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-center">
            <p className="text-2xl font-bold text-white">{totalEngineers}</p>
            <p className="text-xs text-gray-400">Engineers</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {cards.map(team => (
          <TeamHealthCard
            key={team.team}
            team={team.team}
            display={team.display}
            engineerCount={team.engineer_count}
            activeMrs={team.active_mrs}
            doraLevel={team.dora_level}
            warnings={team.warnings}
            inProgressEpics={epicsByProject[team.jira_project ?? ''] ?? []}
            days={days}
            delta={deltas[team.team] ?? null}
            sparklineData={sparklines[team.team]}
            onClickEngineers={() => navigate(`/engineers?team=${team.team}`)}
            onClickMrs={() => navigate(`/activity?team=${encodeURIComponent(team.team)}&days=${days}&state=opened`)}
            onClickAlerts={() => navigate(`/alerts?team=${team.team}`)}
            onClickEpics={() => navigate(`/jira?team=${encodeURIComponent(team.jira_project ?? '')}`)}
          />
        ))}
      </div>
    </div>
  )
}
