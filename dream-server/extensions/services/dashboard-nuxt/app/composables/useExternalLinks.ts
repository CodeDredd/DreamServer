// Externe Quick-Links in der Sidebar.
//
// Quelle: dashboard-api liefert
//   GET /api/external-links     - statische Plugins + Service-Discovery
//   GET /api/service-tokens     - per-Service-Tokens (z.B. OpenClaw)
//
// Healthy-Marker kommt aus useSystemStore: ein Link gilt als "open"
// wenn ein Service mit Match-Bedingung in `status.services` mit
// `status === 'healthy'` existiert.

import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useApi } from '~/composables/useApi'
import { useSystemStore } from '~/stores/system'

export interface ExternalLink {
  id: string
  label: string
  port: number
  ui_path?: string
  icon?: string
  alwaysHealthy?: boolean
  healthNeedles?: string[]
}

export interface SidebarExternalLink {
  key: string
  label: string
  icon: string
  url: string
  healthy: boolean
}

const ICON_MAP: Record<string, string> = {
  MessageSquare: 'i-lucide-message-square',
  Network: 'i-lucide-network',
  Bot: 'i-lucide-bot',
  Terminal: 'i-lucide-terminal',
  Search: 'i-lucide-search',
  Image: 'i-lucide-image',
  ExternalLink: 'i-lucide-external-link',
}

function resolveIcon(raw?: string): string {
  if (!raw) return ICON_MAP.ExternalLink
  if (raw.startsWith('i-')) return raw // bereits Iconify-Name
  return ICON_MAP[raw] || ICON_MAP.ExternalLink
}

let initialized = false
const apiLinks = ref<ExternalLink[]>([])
const serviceTokens = ref<Record<string, string>>({})

async function initOnce() {
  if (initialized) return
  initialized = true
  const api = useApi()
  try {
    apiLinks.value = await api.get<ExternalLink[]>('/api/external-links')
  }
  catch {
    apiLinks.value = []
  }
  try {
    serviceTokens.value = await api.get<Record<string, string>>('/api/service-tokens')
  }
  catch {
    serviceTokens.value = {}
  }
}

export function useExternalLinks() {
  const store = useSystemStore()
  const { status } = storeToRefs(store)

  if (typeof window !== 'undefined') {
    void initOnce()
  }

  function externalUrl(port: number): string {
    if (typeof window !== 'undefined') {
      return `http://${window.location.hostname}:${port}`
    }
    return `http://localhost:${port}`
  }

  const links = computed<SidebarExternalLink[]>(() => {
    const services = status.value?.services ?? []
    return apiLinks.value.map((raw) => {
      const healthy = raw.alwaysHealthy
        ? true
        : (raw.healthNeedles ?? []).some(n =>
            services.some(s =>
              ((s.id || '').toLowerCase().includes(n.toLowerCase())
                || (s.name || '').toLowerCase().includes(n.toLowerCase()))
              && s.status === 'healthy',
            ),
          )

      let url = externalUrl(raw.port)
      if (raw.ui_path && raw.ui_path !== '/') {
        url += raw.ui_path
      }
      // OpenClaw bekommt seinen Token als Query angehaengt — damit
      // SSO-loses Embedding klappt (siehe React-Sidebar.jsx Zeile 41).
      if (raw.id === 'openclaw' && serviceTokens.value.openclaw) {
        url += `${url.includes('?') ? '&' : '?'}token=${serviceTokens.value.openclaw}`
      }

      return {
        key: raw.id,
        label: raw.label,
        icon: resolveIcon(raw.icon),
        url,
        healthy,
      }
    })
  })

  const visibleLinks = computed(() =>
    links.value.filter(l => l.healthy),
  )

  return {
    links,
    visibleLinks,
    serviceTokens,
    refresh: () => {
      initialized = false
      return initOnce()
    },
  }
}

