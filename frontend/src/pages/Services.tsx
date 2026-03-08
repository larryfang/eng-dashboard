import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getPortServices, syncPortServices, enrichPortVersions, getConfig } from '../api/client'
import type { OrgConfig, TeamConfig } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatDistanceToNow } from 'date-fns'

interface PortService {
  id: string
  title: string
  department?: string
  system?: string
  domain?: string
  team?: string            // Port team identifier, e.g. "saas_ecommerce"
  language?: string
  language_version?: string
  url?: string
  publicly_exposed?: boolean
  service_criticality?: string
}

// Friendly display names for Port domain identifiers.
// Customize these to match your Port.io domain taxonomy.
const DOMAIN_LABELS: Record<string, string> = {}
function domainLabel(id?: string) {
  if (!id) return '(unresolved)'
  return DOMAIN_LABELS[id] ?? id
}

interface PortResponse {
  services: PortService[]
  count: number
  from_cache?: boolean
  synced_at?: string
}

// Group services: domain → portTeamId → services[]
function buildTree(services: PortService[]): Map<string, Map<string, PortService[]>> {
  const tree = new Map<string, Map<string, PortService[]>>()
  for (const svc of services) {
    const domain = svc.domain ?? '(unresolved)'
    const team = svc.team ?? '(unassigned)'
    if (!tree.has(domain)) tree.set(domain, new Map())
    const teamMap = tree.get(domain)!
    if (!teamMap.has(team)) teamMap.set(team, [])
    teamMap.get(team)!.push(svc)
  }
  return tree
}

function criticalityColor(c?: string) {
  if (!c) return 'bg-gray-700/50 text-gray-400'
  switch (c.toLowerCase()) {
    case 'critical': return 'bg-red-500/20 text-red-400'
    case 'high':     return 'bg-orange-500/20 text-orange-400'
    case 'medium':   return 'bg-yellow-500/20 text-yellow-400'
    default:         return 'bg-gray-700/50 text-gray-400'
  }
}

function langColor(lang?: string) {
  if (!lang) return 'text-gray-600'
  switch (lang.toLowerCase()) {
    case 'java':       return 'text-orange-400'
    case 'kotlin':     return 'text-purple-400'
    case 'typescript': return 'text-blue-400'
    case 'node':       return 'text-green-400'
    case 'python':     return 'text-yellow-400'
    case 'go':         return 'text-cyan-400'
    case 'ruby':       return 'text-red-400'
    default:           return 'text-gray-500'
  }
}

export default function ServicesPage() {
  const [data, setData] = useState<PortResponse | null>(null)
  const [orgConfig, setOrgConfig] = useState<OrgConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [notConfigured, setNotConfigured] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [enriching, setEnriching] = useState(false)
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const enrichTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [selectedDomain, setSelectedDomain] = useState<string>('')
  const [selectedTeam, setSelectedTeam] = useState<string>('')
  const [expandedDomain, setExpandedDomain] = useState<string | null>(null)
  const [expandedTeams, setExpandedTeams] = useState<Set<string>>(new Set())

  // Build portTeamId → TeamConfig mapping from org config
  // Maps Port team identifiers to org config teams
  const portTeamMap = useMemo<Record<string, TeamConfig>>(() => {
    const map: Record<string, TeamConfig> = {}
    for (const t of orgConfig?.teams ?? []) {
      if (t.port_team_id) map[t.port_team_id] = t
    }
    return map
  }, [orgConfig])

  // Resolve a Port team ID to a human-readable display name
  const teamLabel = (portTeamId?: string): string => {
    if (!portTeamId) return '(unassigned)'
    const t = portTeamMap[portTeamId]
    if (t) return t.scrum_name ? `${t.name} (${t.scrum_name})` : t.name
    return portTeamId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }

  const load = () => {
    setLoading(true)
    setError(null)
    setNotConfigured(false)
    Promise.all([
      getPortServices(),
      getConfig(),
    ])
      .then(([svcRes, cfgRes]) => {
        const d = svcRes.data as PortResponse
        const list = Array.isArray(d) ? { services: d, count: (d as PortService[]).length } : d
        setData(list as PortResponse)
        setOrgConfig(cfgRes.data)
        setNotConfigured(false)
        // Auto-expand the first domain
        const first = (list as PortResponse).services?.[0]?.domain ?? null
        if (first) setExpandedDomain(first)
      })
      .catch(err => {
        if (err?.response?.status === 503 || err?.response?.status === 404) {
          setNotConfigured(true)
          setError(null)
        } else {
          setNotConfigured(false)
          setError(err?.message ?? 'Failed to load services')
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    return () => {
      if (syncTimerRef.current) clearTimeout(syncTimerRef.current)
      if (enrichTimerRef.current) clearTimeout(enrichTimerRef.current)
    }
  }, [])

  // Two-way sync: URL ?q= ↔ search state
  const urlQ = searchParams.get('q') ?? ''
  useEffect(() => {
    if (urlQ) setSearch(urlQ)
  }, [urlQ])
  useEffect(() => {
    const currentQ = searchParams.get('q') ?? ''
    if (search !== currentQ) {
      if (search) {
        setSearchParams({ q: search }, { replace: true })
      } else if (currentQ) {
        setSearchParams({}, { replace: true })
      }
    }
  }, [search, setSearchParams])

  // Auto-expand all domains/teams when search filter is active (e.g. from Cmd+K ?q=)
  useEffect(() => {
    if (search && data?.services) {
      const lq = search.toLowerCase()
      const matched = data.services.filter(s =>
        s.title.toLowerCase().includes(lq) || s.language?.toLowerCase().includes(lq) ||
        s.language_version?.toLowerCase().includes(lq) || s.team?.toLowerCase().includes(lq) ||
        teamLabel(s.team).toLowerCase().includes(lq) || s.system?.toLowerCase().includes(lq) ||
        s.domain?.toLowerCase().includes(lq) || domainLabel(s.domain).toLowerCase().includes(lq)
      )
      if (matched.length > 0) {
        const tree = buildTree(matched)
        const teamKeys = new Set<string>()
        let firstDomain: string | null = null
        for (const [domain, teamMap] of tree) {
          if (!firstDomain) firstDomain = domain
          for (const teamId of teamMap.keys()) teamKeys.add(`${domain}::${teamId}`)
        }
        setExpandedDomain(firstDomain)
        setExpandedTeams(teamKeys)
      }
    }
  }, [data, search])

  const handleSync = () => {
    setSyncing(true)
    syncPortServices()
      .then(() => { syncTimerRef.current = setTimeout(() => { load(); setSyncing(false) }, 10_000) })
      .catch(() => setSyncing(false))
  }

  const handleEnrichVersions = () => {
    setEnriching(true)
    enrichPortVersions()
      .then(() => { enrichTimerRef.current = setTimeout(() => { load(); setEnriching(false) }, 30_000) })
      .catch(() => setEnriching(false))
  }

  const toggleTeam = (key: string) => {
    setExpandedTeams(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  if (loading) return <LoadingSpinner text="Loading service catalog..." />

  if (notConfigured) {
    return (
      <div className="p-6">
        <h2 className="text-xl font-bold text-white mb-4">Service Catalog</h2>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center space-y-3">
          <div className="w-12 h-12 bg-gray-800 rounded-full flex items-center justify-center mx-auto">
            <span className="text-gray-500 text-2xl">S</span>
          </div>
          <p className="text-white font-medium">Connect Port.io to see service catalog</p>
          <p className="text-gray-400 text-sm max-w-xs mx-auto">
            Add PORT_CLIENT_ID and PORT_CLIENT_SECRET to your .env to enable the catalog.
          </p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">{error}</div>
      </div>
    )
  }

  const services = data?.services ?? []

  // Domains: unique values from actual service data
  const allDomains = Array.from(new Set(services.map(s => s.domain ?? '(unresolved)'))).sort()

  // Teams: come from org config (always shows all 8 teams, even before sync)
  const orgTeams: TeamConfig[] = orgConfig?.teams ?? []

  const q = search.toLowerCase()
  const filtered = services.filter(s => {
    if (selectedDomain && (s.domain ?? '(unresolved)') !== selectedDomain) return false
    // Filter by org team: match against the team's port_team_id
    if (selectedTeam) {
      const matchedOrgTeam = orgTeams.find(t => (t.slug ?? t.key.toLowerCase()) === selectedTeam)
      if (!matchedOrgTeam?.port_team_id || s.team !== matchedOrgTeam.port_team_id) return false
    }
    if (q) {
      return !!(
        s.title.toLowerCase().includes(q) ||
        s.team?.toLowerCase().includes(q) ||
        teamLabel(s.team).toLowerCase().includes(q) ||
        s.system?.toLowerCase().includes(q) ||
        s.domain?.toLowerCase().includes(q) ||
        domainLabel(s.domain).toLowerCase().includes(q) ||
        s.language?.toLowerCase().includes(q) ||
        s.language_version?.toLowerCase().includes(q)
      )
    }
    return true
  })

  const tree = buildTree(filtered)
  const domains = Array.from(tree.keys()).sort()

  const domainCount = tree.size
  const teamCount = Array.from(tree.values()).reduce((n, m) => n + m.size, 0)
  const versionedCount = services.filter(s => s.language_version).length

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Service Catalog</h2>
          <p className="text-gray-400 text-sm mt-0.5">
            {filtered.length} service{filtered.length !== 1 ? 's' : ''} ·{' '}
            {domainCount} domain{domainCount !== 1 ? 's' : ''} ·{' '}
            {teamCount} team{teamCount !== 1 ? 's' : ''} ·{' '}
            {versionedCount} versioned
            {data?.synced_at && (
              <span className="ml-2 text-gray-600">
                · cached {formatDistanceToNow(new Date(data.synced_at), { addSuffix: true })}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleEnrichVersions}
            disabled={enriching}
            title="Scan GitLab repos to detect language versions (e.g. Java 17, Python 3.11)"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-gray-400 text-xs transition-colors disabled:opacity-50"
          >
            <span className={enriching ? 'animate-spin inline-block' : ''}>⚙</span>
            {enriching ? 'Scanning versions…' : 'Scan Versions'}
          </button>
          <button
            onClick={handleSync}
            disabled={syncing}
            title="Re-fetch all services from Port.io"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-gray-400 text-xs transition-colors disabled:opacity-50"
          >
            <span className={syncing ? 'animate-spin inline-block' : ''}>↻</span>
            {syncing ? 'Syncing…' : 'Sync Port'}
          </button>
        </div>
      </div>

      {/* Filters row */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search by name, language (e.g. Java, Python)…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="flex-1 min-w-[220px] bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-gray-200 text-sm placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
        <select
          value={selectedDomain}
          onChange={e => { setSelectedDomain(e.target.value); setExpandedDomain(e.target.value || null) }}
          className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
        >
          <option value="">All Domains</option>
          {allDomains.map(d => (
            <option key={d} value={d}>{domainLabel(d)}</option>
          ))}
        </select>
        <select
          value={selectedTeam}
          onChange={e => setSelectedTeam(e.target.value)}
          className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
        >
          <option value="">All Teams</option>
          {orgTeams.map(t => (
            <option key={t.key} value={t.slug ?? t.key.toLowerCase()}>
              {t.scrum_name ? `${t.name} (${t.scrum_name})` : t.name}
            </option>
          ))}
        </select>
      </div>

      {/* No services yet */}
      {services.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center space-y-2">
          <p className="text-gray-400 text-sm">No services synced yet.</p>
          <p className="text-gray-600 text-xs">Click <strong className="text-gray-400">Sync Port</strong> to fetch the service catalog from Port.io.</p>
        </div>
      )}

      {/* Domain sections */}
      {services.length > 0 && domains.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500 text-sm">
          No services match the current filters
        </div>
      ) : (
        domains.map(domain => {
          const teamMap = tree.get(domain)!
          const domainTotal = Array.from(teamMap.values()).reduce((n, a) => n + a.length, 0)
          const isOpen = expandedDomain === domain

          return (
            <div key={domain} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              {/* Domain header */}
              <button
                onClick={() => setExpandedDomain(isOpen ? null : domain)}
                className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-800/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-white font-semibold">{domainLabel(domain)}</span>
                  <span className="text-xs bg-gray-800 border border-gray-700 text-gray-400 px-2 py-0.5 rounded-full">
                    {domainTotal} services
                  </span>
                  <span className="text-xs text-gray-600">
                    {teamMap.size} team{teamMap.size !== 1 ? 's' : ''}
                  </span>
                </div>
                <span className="text-gray-500 text-xs">{isOpen ? '▲' : '▼'}</span>
              </button>

              {/* Team groups */}
              {isOpen && (
                <div className="border-t border-gray-800 divide-y divide-gray-800/50">
                  {Array.from(teamMap.entries())
                    .sort(([a], [b]) => teamLabel(a).localeCompare(teamLabel(b)))
                    .map(([portTeamId, svcs]) => {
                      const teamKey = `${domain}::${portTeamId}`
                      const isTeamOpen = expandedTeams.has(teamKey)

                      return (
                        <div key={portTeamId}>
                          {/* Team row */}
                          <button
                            onClick={() => toggleTeam(teamKey)}
                            className="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-800/30 transition-colors"
                          >
                            <div className="flex items-center gap-3">
                              <span className="text-gray-300 text-sm font-medium">{teamLabel(portTeamId)}</span>
                              <span className="text-xs bg-gray-800/60 text-gray-500 px-1.5 py-0.5 rounded">
                                {svcs.length}
                              </span>
                            </div>
                            <span className="text-gray-700 text-xs">{isTeamOpen ? '▲' : '▼'}</span>
                          </button>

                          {/* Service grid for this team */}
                          {isTeamOpen && (
                            <div className="px-5 pb-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
                              {svcs
                                .sort((a, b) => a.title.localeCompare(b.title))
                                .map(svc => (
                                  <div
                                    key={svc.id}
                                    className="bg-gray-800/40 border border-gray-700/50 rounded-lg px-3 py-2 flex items-start justify-between gap-2"
                                  >
                                    <div className="min-w-0 flex-1">
                                      {svc.url ? (
                                        <a
                                          href={svc.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="text-blue-400 hover:text-blue-300 text-xs font-medium truncate block"
                                        >
                                          {svc.title}
                                        </a>
                                      ) : (
                                        <p className="text-gray-200 text-xs font-medium truncate">{svc.title}</p>
                                      )}
                                      <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                                        {svc.language_version ? (
                                          <span className={`text-xs ${langColor(svc.language)}`}>
                                            {svc.language_version}
                                          </span>
                                        ) : svc.language && svc.language !== 'Unknown' ? (
                                          <span className={`text-xs ${langColor(svc.language)}`}>
                                            {svc.language}
                                          </span>
                                        ) : null}
                                        {svc.system && (
                                          <span className="text-gray-700 text-xs truncate max-w-[120px]" title={svc.system}>
                                            {svc.system}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                    <div className="flex flex-col items-end gap-1 shrink-0">
                                      {svc.service_criticality && (
                                        <span className={`text-xs px-1.5 py-0.5 rounded ${criticalityColor(svc.service_criticality)}`}>
                                          {svc.service_criticality}
                                        </span>
                                      )}
                                      {svc.publicly_exposed && (
                                        <span className="text-xs text-blue-500">public</span>
                                      )}
                                    </div>
                                  </div>
                                ))}
                            </div>
                          )}
                        </div>
                      )
                    })}
                </div>
              )}
            </div>
          )
        })
      )}
    </div>
  )
}
