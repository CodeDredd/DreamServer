// /api/setup/* — Server-authoritative First-Run-Gating.
// Siehe `dashboard/src/hooks/useFirstRun.js` für die Failure-Mode-
// Begründung (Default = NICHT first-run, damit der Wizard nicht bei
// jedem API-Hick­up aufpoppt).

import { defineStore } from 'pinia'
import { useApi } from '~/composables/useApi'
import type { SetupStatus } from '~/types/api'

interface SetupState {
  firstRun: boolean
  loading: boolean
  error: string | null
  raw: SetupStatus | null
}

export const useSetupStore = defineStore('setup', {
  state: (): SetupState => ({
    firstRun: false,
    loading: true,
    error: null,
    raw: null,
  }),

  actions: {
    async refresh() {
      this.loading = true
      const api = useApi()
      try {
        const data = await api.get<SetupStatus>('/api/setup/status')
        this.raw = data
        this.firstRun = Boolean(data.first_run)
        this.error = null
      }
      catch (err: unknown) {
        this.firstRun = false
        this.error = (err as Error).message
      }
      finally {
        this.loading = false
      }
    },

    async complete(payload: Record<string, unknown> = {}) {
      const api = useApi()
      await api.post('/api/setup/complete', payload)
      await this.refresh()
    },
  },
})

