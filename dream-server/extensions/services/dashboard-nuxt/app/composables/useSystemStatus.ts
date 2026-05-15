// React-Hook-Pendant zu `useSystemStatus`. Polling 5 s. Mehrfache
// Aufrufe in derselben App-Session teilen sich denselben Pinia-Store —
// der Polling-Timer wird nur einmal pro App-Lifetime gestartet (Lock
// im `system` Store via `lastUpdated !== null`).

import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'
import { usePolling } from '~/composables/usePolling'

const POLL_INTERVAL = 5000

let started = false

export function useSystemStatus() {
  const store = useSystemStore()

  if (!started) {
    started = true
    usePolling(() => store.fetchStatus(), POLL_INTERVAL)
  }

  const { status, loading, error, lastUpdated } = storeToRefs(store)
  return {
    status,
    loading,
    error,
    lastUpdated,
    refresh: () => store.fetchStatus(),
  }
}

