// System-Store — duenne UI-Schicht ueber dem SystemRepository.
//
// Service-Inventar lebt im Pinia-ORM-Store (Service-Model + SystemRepository,
// `useRepo(Service).all()` / `useRepo(SystemRepository).hasHealthy(...)`).
// Hier verbleiben nur Dinge, die NICHT relational sind:
//   * gpu/ram/bootstrap-Snapshot vom letzten /api/status-Aufruf
//   * Polling-Status (loading/error/lastUpdated)
//   * Versionsinfo + dismissedUpdate (User-Praeferenz)
//
// Das `services`-Getter delegiert ans ORM-Repo — single source of truth.

import { defineStore } from 'pinia'
import { useRepo } from 'pinia-orm'
import Service from '~~/store/models/Service'
import SystemRepository from '~~/store/repositories/SystemRepository'
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
    /** Service-Liste aus dem ORM-Store. */
    services: () => useRepo(Service).orderBy('name').get(),
    gpu: state => state.status?.gpu ?? null,
    ram: state => state.status?.ram ?? null,
    bootstrap: state => state.status?.bootstrap ?? null,
    serviceIds: () =>
      useRepo(Service).all().map(s => (s.id || s.name || '').toLowerCase()).filter(Boolean),
    /** Sidebar-Predikat — nutzt den Repo-Helper. */
    hasService: () => (needle: string) => useRepo(SystemRepository).has(needle),
    hasHealthyService: () => (needle: string) => useRepo(SystemRepository).hasHealthy(needle),
    updateAvailable: state => Boolean(
      state.version?.update_available
      && state.version.latest
      && state.version.latest !== state.dismissedUpdate,
    ),
  },

  actions: {
    async fetchStatus() {
      try {
        this.status = await useRepo(SystemRepository).api().fetchStatus()
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
      try {
        this.version = await useRepo(SystemRepository).api().fetchVersion()
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

