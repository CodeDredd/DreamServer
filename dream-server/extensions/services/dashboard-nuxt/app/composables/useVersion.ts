// React-Hook-Pendant zu `useVersion`. Initial einmal sofort, dann
// alle 30 min (siehe `dashboard/src/hooks/useVersion.js`).

import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'
import { usePolling } from '~/composables/usePolling'

const POLL_INTERVAL = 30 * 60 * 1000 // 30 min

let started = false

export function useVersion() {
  const store = useSystemStore()

  if (!started) {
    started = true
    store.hydrateDismissedUpdate()
    usePolling(() => store.fetchVersion(), POLL_INTERVAL)
  }

  const { version, versionError, dismissedUpdate, updateAvailable } = storeToRefs(store)
  return {
    version,
    error: versionError,
    dismissedUpdate,
    updateAvailable,
    dismissUpdate: () => store.dismissUpdate(),
    refresh: () => store.fetchVersion(),
  }
}

/** One-shot trigger to invoke a server update action. */
export async function triggerUpdate(action: string) {
  const { post } = useApi()
  return await post('/api/update', { action })
}

