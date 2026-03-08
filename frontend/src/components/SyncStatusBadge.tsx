import { formatDistanceToNow } from 'date-fns'

interface SyncInfo {
  last_synced_at: string | null
  next_sync_at?: string | null
  is_stale: boolean
  status: string
  records_synced?: number
}

interface Props {
  syncInfo?: SyncInfo | null
  onRefresh: (force_full?: boolean) => void
  loading?: boolean
  schedulerRunning?: boolean
  schedulerPaused?: boolean
}

export default function SyncStatusBadge({ syncInfo, onRefresh, loading, schedulerRunning, schedulerPaused }: Props) {
  if (!syncInfo) return null
  const isSyncing = loading || syncInfo.status === 'syncing'

  const label = syncInfo.last_synced_at
    ? `Synced ${formatDistanceToNow(new Date(syncInfo.last_synced_at), { addSuffix: true })}`
    : 'Never synced'

  const nextLabel = syncInfo.next_sync_at
    ? `Next in ${formatDistanceToNow(new Date(syncInfo.next_sync_at))}`
    : null

  return (
    <div className="flex items-center gap-2 text-xs text-gray-500">
      <span className={syncInfo.is_stale ? 'text-yellow-500' : 'text-gray-500'}>
        {label}
      </span>
      {schedulerRunning && !schedulerPaused && (
        <span className="flex items-center gap-1 text-green-500" title={nextLabel ?? 'Auto-sync active'}>
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
          Auto
        </span>
      )}
      {schedulerPaused && (
        <span className="text-yellow-500" title="Scheduler paused">
          Paused
        </span>
      )}
      {nextLabel && !isSyncing && (
        <span className="text-gray-600" title="Next automatic refresh">
          {nextLabel}
        </span>
      )}
      <button
        onClick={() => onRefresh(false)}
        disabled={isSyncing}
        className="text-blue-400 hover:text-blue-300 disabled:opacity-40 transition-colors"
      >
        {isSyncing ? 'Syncing…' : '↻ Refresh'}
      </button>
      {!isSyncing && (
        <button
          onClick={() => onRefresh(true)}
          title="Clear cached data and re-sync from GitLab"
          className="text-orange-400 hover:text-orange-300 transition-colors"
        >
          ⟳ Reset
        </button>
      )}
    </div>
  )
}
