// Extensions-Composable (Phase 4 Welle B.5).
//
// Pendant zu dashboard/src/pages/Extensions.jsx (~1255 LoC) — kapselt:
//   * /api/extensions/catalog (manueller Refresh, kein Auto-Poll: catalog
//     ist teuer wegen Health-Probes; React-Variante macht's auch nur
//     on-mount + nach Mutationen).
//   * /api/extensions/{id}/progress — per-Service Polling (3s) während
//     'installing' / 'setting_up' / 'error', mit Recovery-Tracker
//     der nach 3 aufeinanderfolgenden Fetch-Fehlern den Banner setzt.
//   * Mutationen install/enable/disable/uninstall/purge mit Toast und
//     automatischem Catalog-Refresh.
//
// Module-cached state, started-Lock identisch zu den anderen Welle-B-
// Composables.

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import type {
  ExtensionEntry,
  ExtensionMutationResult,
  ExtensionProgress,
  ExtensionsCatalogResponse,
  ExtensionsCatalogSummary,
} from '~/types/api'

const PROGRESS_POLL_MS = 3000
const PROGRESS_FAIL_THRESHOLD = 3

// API/backend services with no user-facing web UI — show badge instead of port link.
export const HEADLESS_EXTENSIONS = new Set(['embeddings', 'tts', 'whisper', 'privacy-shield'])

const catalog: Ref<ExtensionsCatalogResponse | null> = ref(null)
const loading = ref(true)
const refreshing = ref(false)
const error: Ref<string | null> = ref(null)
const mutating: Ref<string | null> = ref(null)
const pollingLost = ref(false)
const progressMap: Ref<Record<string, ExtensionProgress>> = ref({})

const activePollers: Record<string, ReturnType<typeof setInterval>> = {}
const progressFails: Record<string, number> = {}

let started = false

export type MutationAction = 'install' | 'enable' | 'disable' | 'uninstall' | 'purge'

export interface MutationOptions {
  autoEnableDeps?: boolean
}

export interface MutationOutcome {
  ok: boolean
  /** "missing_dependencies" surface for the auto-enable confirm dialog. */
  missingDependencies?: string[]
  ext?: ExtensionEntry
}

export function friendlyError(detail: unknown): string {
  if (typeof detail !== 'string') return String(detail ?? 'Unknown error')
  if (detail.includes('build context') || detail.includes('local build'))
    return 'This extension requires a local build and cannot be installed through the portal yet.'
  if (detail.includes('already installed')) return 'This extension is already installed.'
  if (detail.includes('already enabled')) return 'This extension is already enabled.'
  if (detail.includes('already disabled')) return 'This extension is already disabled.'
  if (detail.includes('Disable extension before')) return 'Please disable this extension before removing it.'
  if (detail.includes('still enabled')) return 'Please disable this extension before purging its data.'
  if (detail.includes('No data directory')) return 'No data directory found for this extension.'
  return detail
}

export function useExtensions() {
  const api = useApi()
  const toast = useToast()

  async function refresh() {
    refreshing.value = true
    if (!catalog.value) loading.value = true
    try {
      const data = await api.get<ExtensionsCatalogResponse>('/api/extensions/catalog')
      catalog.value = data
      error.value = null
      // Auto-attach pollers for any in-flight installs (page reload case).
      for (const ext of data.extensions ?? []) {
        if (ext.status === 'installing' || ext.status === 'setting_up') {
          pollProgress(ext.id)
        }
        else if (ext.status === 'error') {
          // One-shot fetch so the card shows the error message after refresh.
          void fetchProgressOnce(ext.id)
        }
      }
    }
    catch (err: unknown) {
      error.value = (err as Error).message || 'Failed to load extensions catalog'
    }
    finally {
      loading.value = false
      refreshing.value = false
    }
  }

  async function fetchProgressOnce(serviceId: string): Promise<void> {
    try {
      const data = await api.get<ExtensionProgress>(`/api/extensions/${serviceId}/progress`)
      if (data.status === 'error') {
        progressMap.value = { ...progressMap.value, [serviceId]: data }
      }
    }
    catch { /* ignore */ }
  }

  function stopPoller(serviceId: string) {
    const handle = activePollers[serviceId]
    if (handle) {
      clearInterval(handle)
      delete activePollers[serviceId]
    }
    delete progressFails[serviceId]
  }

  function pollProgress(serviceId: string) {
    if (activePollers[serviceId]) return
    progressFails[serviceId] = 0
    activePollers[serviceId] = setInterval(async () => {
      try {
        const data = await api.get<ExtensionProgress>(`/api/extensions/${serviceId}/progress`)
        progressFails[serviceId] = 0
        if (pollingLost.value) pollingLost.value = false
        if (data.status === 'idle') return
        progressMap.value = { ...progressMap.value, [serviceId]: data }

        if (data.status === 'error') {
          stopPoller(serviceId)
          toast.add({
            title: 'Installation failed',
            description: data.error || 'The installer reported an error.',
            color: 'error',
            duration: 8000,
          })
          const next = { ...progressMap.value }; delete next[serviceId]; progressMap.value = next
          await refresh()
          return
        }

        if (data.status === 'started') {
          // Refresh catalog so we can decide if healthcheck has settled
          // ('enabled' / 'cli_installed') or whether we keep polling.
          try {
            const cat = await api.get<ExtensionsCatalogResponse>('/api/extensions/catalog')
            catalog.value = cat
            const ext = cat.extensions?.find(e => e.id === serviceId)
            if (ext && (ext.status === 'enabled' || ext.status === 'cli_installed')) {
              stopPoller(serviceId)
              const successText = ext.status === 'cli_installed'
                ? `${ext.name || 'Extension'} installed — run via "docker compose run --rm ${serviceId}".`
                : 'Extension installed and started.'
              toast.add({ title: 'Done', description: successText, color: 'success', duration: 5000 })
              const next = { ...progressMap.value }; delete next[serviceId]; progressMap.value = next
            }
          }
          catch { /* ignore single fetch err — outer recovery counter handles it */ }
        }
      }
      catch (err) {
        progressFails[serviceId] = (progressFails[serviceId] || 0) + 1
        if (progressFails[serviceId] >= PROGRESS_FAIL_THRESHOLD) {
          pollingLost.value = true
          // Try to recover catalog state — if backend is back, next poll clears banner.
          void refresh()
        }
        // eslint-disable-next-line no-console
        console.warn('extensions: progress poll failed', serviceId, err)
      }
    }, PROGRESS_POLL_MS)
  }

  async function mutate(
    serviceId: string,
    action: MutationAction,
    opts: MutationOptions = {},
  ): Promise<MutationOutcome> {
    mutating.value = serviceId
    try {
      let url: string
      if (action === 'uninstall') url = `/api/extensions/${serviceId}`
      else if (action === 'purge') url = `/api/extensions/${serviceId}/data`
      else url = `/api/extensions/${serviceId}/${action}`

      if (action === 'enable' && opts.autoEnableDeps) url += '?auto_enable_deps=true'

      const isDelete = action === 'uninstall' || action === 'purge'
      const body = action === 'purge' ? { confirm: true } : undefined

      try {
        const data = isDelete
          ? await api.delete<ExtensionMutationResult>(url, { body })
          : await api.post<ExtensionMutationResult>(url, body)

        if (action === 'install' || action === 'enable') {
          await refresh()
          pollProgress(serviceId)
          toast.add({
            title: action === 'install' ? 'Installing…' : 'Enabling…',
            description: 'Watch the card for progress.',
            color: 'info',
            duration: 4000,
          })
        }
        else {
          let successText = data.message || (
            action === 'uninstall' ? 'Extension removed' : `Extension ${action}d`
          )
          if (action === 'purge') {
            successText = data.message || `Data purged — ${data.size_gb_freed ?? 0} GB freed`
          }
          if (data.data_info) {
            successText += ` Data preserved (${data.data_info.size_gb} GB) — purge to remove.`
          }
          if (data.restart_required) {
            toast.add({
              title: 'Restart required',
              description: `${successText} — restart needed to apply.`,
              color: 'warning',
              duration: 6000,
            })
          }
          else {
            toast.add({ title: 'Done', description: successText, color: 'success', duration: 5000 })
          }
          await refresh()
        }
        return { ok: true }
      }
      catch (err: unknown) {
        const e = err as { status?: number, data?: { detail?: { missing_dependencies?: string[], message?: string } | string }, message?: string }
        const detail = e.data?.detail
        if (
          action === 'enable'
          && e.status === 400
          && typeof detail === 'object'
          && detail
          && 'missing_dependencies' in detail
          && Array.isArray(detail.missing_dependencies)
        ) {
          const ext = catalog.value?.extensions?.find(x => x.id === serviceId)
          return { ok: false, missingDependencies: detail.missing_dependencies, ext }
        }
        const msg = friendlyError(
          (typeof detail === 'string' ? detail : detail?.message) || e.message || `Failed to ${action}`,
        )
        toast.add({ title: 'Action failed', description: msg, color: 'error', duration: 8000 })
        return { ok: false }
      }
    }
    finally {
      mutating.value = null
    }
  }

  async function fetchLogs(serviceId: string): Promise<string> {
    const data = await api.post<{ logs?: string }>(`/api/extensions/${serviceId}/logs`)
    return data.logs ?? 'No logs available.'
  }

  if (!started) {
    started = true
    void refresh()
  }

  const summary: ComputedRef<ExtensionsCatalogSummary> = computed(
    () => catalog.value?.summary ?? {},
  )
  const extensions: ComputedRef<ExtensionEntry[]> = computed(
    () => catalog.value?.extensions ?? [],
  )
  const agentAvailable = computed(() => catalog.value?.agent_available)
  const gpuBackend = computed(() => catalog.value?.gpu_backend)

  return {
    catalog,
    extensions,
    summary,
    agentAvailable,
    gpuBackend,
    loading,
    refreshing,
    error,
    mutating,
    pollingLost,
    progressMap,
    refresh,
    mutate,
    pollProgress,
    fetchLogs,
  }
}

// ---------- Status presentation helpers (used by the page + Card) -------

export const STATUS_LABELS: Record<string, string> = {
  all: 'All',
  enabled: 'Enabled',
  cli_installed: 'CLI Installed',
  stopped: 'Stopped',
  unhealthy: 'Unhealthy',
  disabled: 'Disabled',
  installing: 'Installing',
  setting_up: 'Setting Up',
  error: 'Error',
  not_installed: 'Not Installed',
  incompatible: 'Incompatible',
}

export const STATUS_DESCRIPTIONS: Record<string, string> = {
  enabled: 'Service is running and healthy',
  cli_installed: 'CLI tool installed — invoke via `docker compose run --rm <service>`',
  disabled: 'Installed but turned off — won’t start on restart',
  stopped: 'Enabled but container is not running',
  unhealthy: 'Container is running but health check is failing — check logs',
  not_installed: 'Available to install from the extension library',
  incompatible: 'Requires a GPU backend not available on this system',
  installing: 'Being downloaded and set up',
  setting_up: 'Running post-install configuration hooks',
  error: 'Installation or startup failed — click for details',
}

export type StatusBadgeColor = 'success' | 'error' | 'warning' | 'info' | 'neutral' | 'primary'

export function statusBadge(status: string): { label: string, color: StatusBadgeColor } {
  switch (status) {
    case 'enabled':
    case 'cli_installed':
      return { label: status.replace('_', ' '), color: 'success' }
    case 'stopped':
    case 'error':
      return { label: status, color: 'error' }
    case 'unhealthy':
    case 'incompatible':
      return { label: status, color: 'warning' }
    case 'installing':
    case 'setting_up':
      return { label: status.replace('_', ' '), color: 'info' }
    case 'disabled':
      return { label: 'disabled', color: 'neutral' }
    case 'not_installed':
      return { label: 'not installed', color: 'neutral' }
    default:
      return { label: status, color: 'neutral' }
  }
}

export const ICON_FALLBACK = 'i-lucide-puzzle'

export const ICON_MAP: Record<string, string> = {
  Database: 'i-lucide-database',
  Cpu: 'i-lucide-cpu',
  Workflow: 'i-lucide-workflow',
  Plug: 'i-lucide-plug',
  Image: 'i-lucide-image',
  MessageSquare: 'i-lucide-message-square',
  Code: 'i-lucide-code',
  FileText: 'i-lucide-file-text',
  Shield: 'i-lucide-shield',
  Globe: 'i-lucide-globe',
  Music: 'i-lucide-music',
  Video: 'i-lucide-video',
  Search: 'i-lucide-search',
  Puzzle: 'i-lucide-puzzle',
  Box: 'i-lucide-box',
}

export function extensionIcon(ext: ExtensionEntry): string {
  const name = ext.features?.[0]?.icon
  if (name && ICON_MAP[name]) return ICON_MAP[name]
  return ICON_FALLBACK
}

export const STATUS_FILTERS = [
  'all',
  'enabled',
  'cli_installed',
  'stopped',
  'unhealthy',
  'disabled',
  'installing',
  'setting_up',
  'error',
  'not_installed',
  'incompatible',
] as const

export type StatusFilter = typeof STATUS_FILTERS[number]

