// System-Store — `/api/status` (alle 5 s) + `/api/version` (alle 30 min).
// Single source of truth für Sidebar-Predicates, BootstrapBanner, KPI-Strip.

import { defineStore } from 'pinia'
import { useApi } from '~/composables/useApi'
import type { SystemStatus, VersionInfo } from '~/types/api'

interface SystemState {
  status: SystemStatus | null
  loading: boolean
  error: string | null
  lastUpdated: number | null
  version: VersionInfo | null
  versionError: string | null
  dismissedUpdate: string | null
}

export const useSystemStore = defineStore('system', {
  state: (): SystemState => ({
    status: null,
    loading: true,
    error: null,
    lastUpdated: null,
    version: null,
    versionError: null,
    dismissedUpdate: null,
  }),

  getters: {
    services: state => state.status?.services ?? [],
    gpu: state => state.status?.gpu ?? null,
    bootstrap: state => state.status?.bootstrap ?? null,
    /** Stable, comparable hash of the service inventory — for sidebar
     *  predicates that need to react to "did service X appear?". */
    serviceIds: (state) => {
      return (state.status?.services ?? [])
        .map(s => (s.id || s.name || '').toLowerCase())
        .filter(Boolean)
    },
    hasService: (state) => {
      return (needle: string) => {
        const n = needle.toLowerCase()
        return (state.status?.services ?? []).some((s) => {
          const id = (s.id || '').toLowerCase()
          const name = (s.name || '').toLowerCase()
          return id.includes(n) || name.includes(n)
        })
      }
    },
    updateAvailable: state => Boolean(
      state.version?.update_available
      && state.version.latest
      && state.version.latest !== state.dismissedUpdate,
    ),
  },

  actions: {
    async fetchStatus() {
      const api = useApi()
      try {
        const data = await api.get<SystemStatus>('/api/status')
        this.status = data
        this.error = null
        this.lastUpdated = Date.now()
      }
      catch (err: unknown) {
        this.error = (err as Error).message
      }
      finally {
        this.loading = false
      }
    },

    async fetchVersion() {
      const api = useApi()
      try {
        this.version = await api.get<VersionInfo>('/api/version')
        this.versionError = null
      }
      catch (err: unknown) {
        this.versionError = (err as Error).message
        this.version = null
      }
    },

    dismissUpdate() {
      if (this.version?.latest) {
        this.dismissedUpdate = this.version.latest
        // Persist between sessions — VueUse `useStorage` would deeply
        // bind; here a one-line write is enough.
        try {
          localStorage.setItem('dream-dismissed-update', this.version.latest)
        }
        catch { /* private mode / quota */ }
      }
    },

    hydrateDismissedUpdate() {
      try {
        this.dismissedUpdate = localStorage.getItem('dream-dismissed-update')
      }
      catch { /* ignore */ }
    },
  },
})

