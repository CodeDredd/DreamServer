// `/api/models` — Polling 30 s. Lifecycle-Aktionen via Store.

import { storeToRefs } from 'pinia'
import { useModelsStore } from '~/stores/models'
import { usePolling } from '~/composables/usePolling'

const POLL_INTERVAL = 30 * 1000

let started = false

export function useModels() {
  const store = useModelsStore()

  if (!started) {
    started = true
    usePolling(() => store.refresh(), POLL_INTERVAL)
  }

  const { models, gpu, currentModel, loading, error, actionLoading } = storeToRefs(store)
  return {
    models,
    gpu,
    currentModel,
    loading,
    error,
    actionLoading,
    refresh: () => store.refresh(),
    download: (id: string) => store.download(id),
    load: (id: string) => store.load(id),
    delete: (id: string) => store.delete(id),
  }
}

