// First-Run-Gating. KEIN Polling — die Page-Middleware
// (`middleware/first-run.global.ts`, kommt in Phase 4 Welle D) refresh()-t
// gezielt nach Wizard-Abschluss.

import { storeToRefs } from 'pinia'
import { useSetupStore } from '~/stores/setup'

let initialized = false

export function useFirstRun() {
  const store = useSetupStore()

  if (!initialized) {
    initialized = true
    void store.refresh()
  }

  const { firstRun, loading, error } = storeToRefs(store)
  return {
    firstRun,
    loading,
    error,
    refresh: () => store.refresh(),
    complete: (cfg?: Record<string, unknown>) => store.complete(cfg),
  }
}

