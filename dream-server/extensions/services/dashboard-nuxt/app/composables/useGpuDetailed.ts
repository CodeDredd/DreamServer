// `/api/gpu/{detailed,history,topology}` — Polling 5 s.
// Pendant zu `dashboard/src/hooks/useGPUDetailed.js`.

import { storeToRefs } from 'pinia'
import { useGpuStore } from '~/stores/gpu'
import { usePolling } from '~/composables/usePolling'

const POLL_INTERVAL = 5000

let started = false

export function useGpuDetailed() {
  const store = useGpuStore()

  if (!started) {
    started = true
    usePolling(() => store.fetchAll(), POLL_INTERVAL)
  }

  const { detailed, history, topology, loading, error } = storeToRefs(store)
  return {
    detailed,
    history,
    topology,
    loading,
    error,
    refresh: () => store.fetchAll(),
  }
}

