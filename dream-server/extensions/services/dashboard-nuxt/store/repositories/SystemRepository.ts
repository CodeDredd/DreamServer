import BaseRepository from '~~/store/BaseRepository'
import Service from '~~/store/models/Service'
import { dreamFetch } from '~/composables/useApi'
import type { SystemStatus, VersionInfo } from '~/types/api'

/**
 * SystemRepository — wrapt /api/status, /api/version und das gesamte
 * Service-Inventar. Pages/Composables rufen ausschliesslich
 * `useRepo(SystemRepository).api().fetchStatus()` auf, niemals
 * direkt $fetch('/api/status').
 *
 * Service-Inventar wird in den Pinia-ORM-Store gespiegelt, sodass
 * Sidebar-Predikate (Finance Guru / Repo Map / Vikunja-Page) und
 * Service-Listen ueber `useRepo(Service).all()` reaktiv abfragbar
 * sind, statt sich auf einen monolithischen "status"-Blob zu stuetzen.
 */
export default class SystemRepository extends BaseRepository<Service> {
  use = Service

  api() {
    const repo = this
    return {
      async fetchStatus(): Promise<SystemStatus> {
        const data = await dreamFetch<SystemStatus>('/api/status')
        // Service-Inventar in den ORM-Store spiegeln. Liste ist
        // autoritativ — fehlende IDs werden geloescht, damit die
        // Sidebar nicht ewig auf einen entfernten Service wartet.
        const incoming = (data.services ?? []).map(s => ({
          id: s.id || s.name,
          name: s.name ?? '',
          status: s.status ?? 'unknown',
          category: s.category ?? 'optional',
          port: s.port ?? 0,
          uptime: s.uptime ?? 0,
          backend: s.backend ?? null,
        }))
        repo.fresh(incoming)
        return data
      },

      async fetchVersion(): Promise<VersionInfo> {
        return await dreamFetch<VersionInfo>('/api/version')
      },

      async triggerUpdate(action: string) {
        return await dreamFetch('/api/update', {
          method: 'POST',
          body: { action },
        })
      },
    }
  }

  /** Sidebar-Predikat-Helper: lebt einen Service mit dieser ID/Namen
   *  und ist er gesund? */
  hasHealthy(needle: string): boolean {
    const n = needle.toLowerCase()
    return this.where(
      (s: Service) =>
        (s.id?.toLowerCase().includes(n) || s.name?.toLowerCase().includes(n))
        && s.status === 'healthy',
    ).get().length > 0
  }

  /** Sidebar-Predikat-Helper: existiert der Service ueberhaupt
   *  (egal in welchem Status)? */
  has(needle: string): boolean {
    const n = needle.toLowerCase()
    return this.where(
      (s: Service) =>
        s.id?.toLowerCase().includes(n) || s.name?.toLowerCase().includes(n),
    ).get().length > 0
  }
}

