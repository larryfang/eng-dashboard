import { lazy, Suspense, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { getConfig } from './api/client'
import { DomainProvider } from './contexts/DomainContext'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const ActivityPage = lazy(() => import('./pages/Activity'))
const AlertsPage = lazy(() => import('./pages/Alerts'))
const Engineers = lazy(() => import('./pages/Engineers'))
const EngineerDetail = lazy(() => import('./pages/EngineerDetail'))
const JiraPage = lazy(() => import('./pages/Jira'))
const DoraPage = lazy(() => import('./pages/Dora'))
const ReportsPage = lazy(() => import('./pages/Reports'))
const ServicesPage = lazy(() => import('./pages/Services'))
const SettingsPage = lazy(() => import('./pages/Settings'))
const Setup = lazy(() => import('./pages/Setup'))

function FullScreenLoader({ text = 'Loading...' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center h-screen bg-gray-950 text-white">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-gray-400">{text}</p>
      </div>
    </div>
  )
}

export default function App() {
  const [configured, setConfigured] = useState<boolean | null>(null)

  useEffect(() => {
    getConfig()
      .then(r => setConfigured(!!r.data?.organization?.name))
      .catch(() => setConfigured(false))
  }, [])

  if (configured === null) return <FullScreenLoader />

  return (
    <ErrorBoundary>
      <BrowserRouter>
      <DomainProvider>
        <Suspense fallback={<FullScreenLoader text="Loading page..." />}>
          <Routes>
            <Route path="/setup/new" element={<Setup onComplete={() => window.location.href = '/dashboard'} isNewDomain />} />
            <Route path="/setup/*" element={<Setup onComplete={() => setConfigured(true)} />} />
            {!configured && <Route path="*" element={<Navigate to="/setup" replace />} />}
            <Route element={<Layout />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/engineers" element={<Engineers />} />
              <Route path="/engineers/:username" element={<EngineerDetail />} />
              <Route path="/jira" element={<JiraPage />} />
              <Route path="/dora" element={<DoraPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/services" element={<ServicesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </Suspense>
      </DomainProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
