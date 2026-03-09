import { createContext, useContext, useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import axios from 'axios'

interface DomainInfo {
  slug: string
  name: string
  description?: string
  team_count?: number
  active: boolean
  is_configured?: boolean
  error?: string
}

interface DomainContextValue {
  activeDomain: DomainInfo | null
  domains: DomainInfo[]
  switchDomain: (slug: string) => Promise<void>
  refreshDomains: () => Promise<void>
}

const DomainContext = createContext<DomainContextValue>({
  activeDomain: null,
  domains: [],
  switchDomain: async () => {},
  refreshDomains: async () => {},
})

export function DomainProvider({ children }: { children: ReactNode }) {
  const [domains, setDomains] = useState<DomainInfo[]>([])
  const [activeDomain, setActiveDomain] = useState<DomainInfo | null>(null)

  const refreshDomains = async () => {
    try {
      const r = await axios.get('/api/domains')
      const list: DomainInfo[] = r.data.domains ?? []
      setDomains(list)
      setActiveDomain(list.find(d => d.active) ?? null)
    } catch {
      // Backend not yet configured — ignore silently
    }
  }

  const switchDomain = async (slug: string) => {
    await axios.post('/api/domains/switch', { slug })
    await refreshDomains()
    // Full reload so all cached dashboard data refreshes for the new domain
    window.location.reload()
  }

  useEffect(() => {
    const fetchInitial = async () => {
      try {
        const r = await axios.get('/api/domains')
        const list: DomainInfo[] = r.data.domains ?? []
        setDomains(list)
        setActiveDomain(list.find(d => d.active) ?? null)
      } catch {
        // Backend not yet configured — ignore silently
      }
    }
    fetchInitial()
  }, [])

  return (
    <DomainContext.Provider value={{ activeDomain, domains, switchDomain, refreshDomains }}>
      {children}
    </DomainContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export const useDomain = () => useContext(DomainContext)
