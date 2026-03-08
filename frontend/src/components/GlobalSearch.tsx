import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, User, Users, GitMerge, TicketCheck, Server, BellRing, Settings2, FileText, X, ArrowRight } from 'lucide-react'
import { globalSearch, type SearchResult } from '../api/client'

const RECENT_KEY = 'globalSearch:recent'
const MAX_RECENT = 8

const CATEGORY_META: Record<string, { label: string; icon: typeof User }> = {
  engineers: { label: 'Engineers', icon: User },
  teams: { label: 'Teams', icon: Users },
  mrs: { label: 'Merge Requests', icon: GitMerge },
  epics: { label: 'Epics', icon: TicketCheck },
  services: { label: 'Services', icon: Server },
}

const VIEW_ALL_ACTIONS: Record<string, (q: string) => SearchResult> = {
  services: (q) => ({
    type: 'service',
    id: '__view_all_services',
    title: 'View all matching services',
    subtitle: `Open Services page filtered by "${q}"`,
    url: `/services?q=${encodeURIComponent(q)}`,
  }),
}

function saveRecent(query: string) {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    const arr: string[] = raw ? JSON.parse(raw) : []
    const deduped = [query, ...arr.filter(q => q !== query)].slice(0, MAX_RECENT)
    localStorage.setItem(RECENT_KEY, JSON.stringify(deduped))
  } catch {
    // localStorage unavailable
  }
}

function getRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

interface Props {
  onClose: () => void
}

export default function GlobalSearch({ onClose }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Record<string, SearchResult[]>>({})
  const [loading, setLoading] = useState(false)
  const [selectedIdx, setSelectedIdx] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const navigate = useNavigate()

  const trimmedQuery = query.trim()
  const displayedResults = trimmedQuery.length >= 2 ? results : {}
  const flatResults: SearchResult[] = []

  for (const cat of Object.keys(CATEGORY_META)) {
    if (displayedResults[cat]?.length) {
      flatResults.push(...displayedResults[cat])
      if (VIEW_ALL_ACTIONS[cat]) {
        flatResults.push(VIEW_ALL_ACTIONS[cat](trimmedQuery))
      }
    }
  }

  const activeSelectedIdx = flatResults.length === 0 ? 0 : Math.min(selectedIdx, flatResults.length - 1)

  useEffect(() => {
    const timer = window.setTimeout(() => inputRef.current?.focus(), 50)
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (trimmedQuery.length < 2) {
      abortRef.current?.abort()
      setLoading(false)
      return
    }

    const timer = window.setTimeout(() => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setLoading(true)
      globalSearch(trimmedQuery, controller.signal)
        .then(res => {
          if (!controller.signal.aborted) {
            setResults(res.data.results)
            setSelectedIdx(0)
          }
        })
        .catch(err => {
          if (err?.name !== 'CanceledError' && !controller.signal.aborted) {
            setResults({})
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 300)

    return () => window.clearTimeout(timer)
  }, [trimmedQuery])

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIdx(i => Math.min(i + 1, Math.max(flatResults.length - 1, 0)))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIdx(i => Math.max(i - 1, 0))
      } else if (e.key === 'Enter' && flatResults.length > 0) {
        e.preventDefault()
        const item = flatResults[activeSelectedIdx]
        if (item) handleSelect(item)
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [activeSelectedIdx, flatResults, onClose])

  const handleSelect = (item: SearchResult) => {
    if (trimmedQuery) saveRecent(trimmedQuery)
    onClose()
    if (item.url) {
      navigate(item.url)
    } else if (item.external_url) {
      window.open(item.external_url, '_blank', 'noopener,noreferrer')
    }
  }

  const recentSearches = getRecent()
  const hasResults = flatResults.length > 0
  const showEmpty = trimmedQuery.length >= 2 && !loading && !hasResults

  let runningIdx = 0

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex justify-center"
      onClick={onClose}
    >
      <div
        className="mt-[15vh] w-full max-w-2xl h-fit bg-gray-900 rounded-xl border border-gray-700 shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800">
          <Search size={18} className={loading ? 'text-blue-400 animate-pulse' : 'text-gray-500'} />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search engineers, teams, MRs, epics, services…"
            className="flex-1 bg-transparent text-white text-sm placeholder-gray-500 outline-none"
          />
          {query && (
            <button onClick={() => setQuery('')} className="text-gray-500 hover:text-gray-300" aria-label="Clear search">
              <X size={16} />
            </button>
          )}
          <kbd className="text-[10px] text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded font-mono border border-gray-700">
            ESC
          </kbd>
        </div>

        <div className="max-h-[60vh] overflow-y-auto">
          {trimmedQuery.length < 2 && !hasResults && (
            <div className="p-4">
              {recentSearches.length > 0 && (
                <div className="mb-4">
                  <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Recent Searches</p>
                  <div className="flex flex-wrap gap-2">
                    {recentSearches.map(recent => (
                      <button
                        key={recent}
                        onClick={() => setQuery(recent)}
                        className="text-xs text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-750 px-2.5 py-1 rounded-md transition-colors"
                      >
                        {recent}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Quick Navigation</p>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Dashboard', path: '/dashboard', Icon: Search },
                  { label: 'Alerts', path: '/alerts', Icon: BellRing },
                  { label: 'Engineers', path: '/engineers', Icon: Users },
                  { label: 'Jira', path: '/jira', Icon: TicketCheck },
                  { label: 'DORA', path: '/dora', Icon: Search },
                  { label: 'Reports', path: '/reports', Icon: FileText },
                  { label: 'Services', path: '/services', Icon: Server },
                  { label: 'Settings', path: '/settings', Icon: Settings2 },
                ].map(({ label, path, Icon }) => (
                  <button
                    key={path}
                    onClick={() => { onClose(); navigate(path) }}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-gray-400 hover:text-white bg-gray-800/50 hover:bg-gray-800 rounded-lg transition-colors"
                  >
                    <Icon size={14} />
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {showEmpty && (
            <div className="p-8 text-center text-gray-500 text-sm">
              No results for "<span className="text-gray-300">{trimmedQuery}</span>"
            </div>
          )}

          {Object.entries(CATEGORY_META).map(([cat, { label, icon: Icon }]) => {
            const items = displayedResults[cat]
            if (!items || items.length === 0) return null

            const startIdx = runningIdx
            const viewAll = VIEW_ALL_ACTIONS[cat] ? VIEW_ALL_ACTIONS[cat](trimmedQuery) : null
            runningIdx += items.length + (viewAll ? 1 : 0)

            return (
              <div key={cat}>
                <div className="px-4 pt-3 pb-1">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wider font-medium">{label}</p>
                </div>
                {items.map((item, i) => {
                  const globalIdx = startIdx + i
                  const isSelected = globalIdx === activeSelectedIdx

                  return (
                    <button
                      key={item.id}
                      onClick={() => handleSelect(item)}
                      onMouseEnter={() => setSelectedIdx(globalIdx)}
                      className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                        isSelected ? 'bg-blue-600/20 text-white' : 'text-gray-300 hover:bg-gray-800/50'
                      }`}
                    >
                      <Icon size={16} className={isSelected ? 'text-blue-400' : 'text-gray-600'} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm truncate">{item.title}</p>
                        {item.subtitle && (
                          <p className="text-xs text-gray-500 truncate">{item.subtitle}</p>
                        )}
                      </div>
                      {item.external_url && !item.url && (
                        <span className="text-[10px] text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">
                          external
                        </span>
                      )}
                    </button>
                  )
                })}
                {viewAll && (() => {
                  const globalIdx = startIdx + items.length
                  const isSelected = globalIdx === activeSelectedIdx

                  return (
                    <button
                      key={viewAll.id}
                      onClick={() => handleSelect(viewAll)}
                      onMouseEnter={() => setSelectedIdx(globalIdx)}
                      className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors ${
                        isSelected ? 'bg-blue-600/20 text-white' : 'text-gray-400 hover:bg-gray-800/50'
                      }`}
                    >
                      <ArrowRight size={14} className={isSelected ? 'text-blue-400' : 'text-gray-600'} />
                      <span className="text-xs">{viewAll.title}</span>
                    </button>
                  )
                })()}
              </div>
            )
          })}
        </div>

        {hasResults && (
          <div className="px-4 py-2 border-t border-gray-800 flex gap-4 text-[11px] text-gray-600">
            <span><kbd className="bg-gray-800 px-1 rounded">↑↓</kbd> navigate</span>
            <span><kbd className="bg-gray-800 px-1 rounded">↵</kbd> open</span>
            <span><kbd className="bg-gray-800 px-1 rounded">esc</kbd> close</span>
          </div>
        )}
      </div>
    </div>
  )
}
