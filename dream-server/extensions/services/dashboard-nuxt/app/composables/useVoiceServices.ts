// Voice services health composable (Phase 4 Welle C.2).
// Pollt /api/voice/status alle 30 s — Pendant zum lokalen
// useVoiceServices()-Hook in dashboard/src/pages/Voice.jsx.

import { ref, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import { usePolling } from '~/composables/usePolling'

const POLL_INTERVAL = 30_000

export interface VoiceServiceProbe {
  status: 'healthy' | 'unhealthy' | 'unknown' | string
  message?: string
}

export interface VoiceServicesStatus {
  available: boolean
  message?: string
  services?: {
    stt?: VoiceServiceProbe
    tts?: VoiceServiceProbe
    livekit?: VoiceServiceProbe
  }
}

const services: Ref<VoiceServicesStatus | null> = ref(null)
const loading = ref(true)

let started = false

export function useVoiceServices() {
  const api = useApi()

  async function refresh() {
    try {
      const data = await api.get<VoiceServicesStatus>('/api/voice/status')
      services.value = data
    }
    catch (err: unknown) {
      // eslint-disable-next-line no-console
      console.error('voice/status fetch failed:', err)
      services.value = { available: false, services: {}, message: 'API unavailable' }
    }
    finally {
      loading.value = false
    }
  }

  if (!started) {
    started = true
    usePolling(refresh, POLL_INTERVAL)
  }

  return { services, loading, refresh }
}

