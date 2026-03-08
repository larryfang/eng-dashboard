import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { LayoutDashboard, BellRing, Users, TicketCheck, BarChart3, Server, Settings2, ChevronDown, Plus, Search, FileText, Rocket } from 'lucide-react'
import { useDomain } from '../contexts/DomainContext'
import GlobalSearch from './GlobalSearch'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/alerts', icon: BellRing, label: 'Alerts' },
  { to: '/engineers', icon: Users, label: 'Engineers' },
  { to: '/jira', icon: TicketCheck, label: 'Jira' },
  { to: '/dora', icon: BarChart3, label: 'DORA' },
  { to: '/reports', icon: FileText, label: 'Reports' },
  { to: '/services', icon: Server, label: 'Services' },
  { to: '/setup/new', icon: Rocket, label: 'Onboarding' },
  { to: '/settings', icon: Settings2, label: 'Settings' },
]

function DomainSwitcher() {
  const { activeDomain, domains, switchDomain } = useDomain()
  const [open, setOpen] = useState(false)

  if (domains.length === 0) return null

  // Single domain — show as a non-interactive label
  if (domains.length === 1) {
    return (
      <div className="px-3 pb-3">
        <span className="block text-xs text-gray-600 font-mono truncate">
          {activeDomain?.name ?? '—'}
        </span>
        <a
          href="/setup/new"
          className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
        >
          <Plus size={11} />
          Add domain
        </a>
      </div>
    )
  }

  return (
    <div className="px-3 pb-3 relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between text-xs text-blue-400 font-mono bg-gray-800 hover:bg-gray-750 px-2 py-1.5 rounded-lg transition-colors"
      >
        <span className="truncate">{activeDomain?.name ?? '—'}</span>
        <ChevronDown size={12} className={`shrink-0 ml-1 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute left-3 right-3 bottom-full mb-1 bg-gray-900 border border-gray-700 rounded-lg shadow-xl z-50">
          {domains.map(d => (
            <button
              key={d.slug}
              onClick={() => {
                setOpen(false)
                switchDomain(d.slug)
              }}
              className={`w-full text-left px-3 py-2 text-xs first:rounded-t-lg hover:bg-gray-800 flex items-center justify-between transition-colors ${
                d.active ? 'text-blue-400' : 'text-gray-400'
              }`}
            >
              <span className="flex items-center gap-1.5 truncate">
                <span className="truncate">{d.name}</span>
              </span>
              {d.active && <span className="text-gray-600 shrink-0 ml-1">✓</span>}
            </button>
          ))}
          <div className="border-t border-gray-800">
            <a
              href="/setup/new"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 w-full px-3 py-2 text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-800 rounded-b-lg transition-colors"
            >
              <Plus size={11} />
              Add domain
            </a>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Layout() {
  const [searchOpen, setSearchOpen] = useState(false)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="flex h-screen bg-gray-950 text-white">
      <aside className="w-56 bg-gray-900 flex flex-col border-r border-gray-800">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-sm font-bold text-blue-400">Engineering Dashboard</h1>
        </div>
        <button
          onClick={() => setSearchOpen(true)}
          className="mx-3 mt-3 flex items-center gap-2 px-3 py-2 text-gray-500 hover:text-gray-300 bg-gray-800/50 hover:bg-gray-800 rounded-lg text-xs transition-colors"
        >
          <Search size={14} />
          <span className="flex-1 text-left">Search...</span>
          <kbd className="text-[10px] bg-gray-700 px-1.5 py-0.5 rounded font-mono">⌘K</kbd>
        </button>
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <DomainSwitcher />
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
      {searchOpen && <GlobalSearch onClose={() => setSearchOpen(false)} />}
    </div>
  )
}
