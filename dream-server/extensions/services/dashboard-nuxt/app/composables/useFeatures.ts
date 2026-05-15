// `/api/features` — Feature-Discovery-Cards (LAN-Web, Chat, Voice, …).
// Polling 15 s wie React-Pendant (`Dashboard.jsx` Zeile 511-530).
// Wird global einmalig gestartet (started-Lock); jede aufrufende
// Component liest aus dem gleichen reactive ref.

import { ref, type Ref } from 'vue'
import type { FeatureItem, FeaturesResponse } from '~/types/api'
import { dreamFetch } from '~/composables/useApi'
import { usePolling } from '~/composables/usePolling'

const POLL_INTERVAL = 15_000

const features: Ref<FeatureItem[]> = ref([])
const error: Ref<string | null> = ref(null)
let started = false

async function fetchFeatures() {
  try {
    const data = await dreamFetch<FeaturesResponse>('/api/features')
    features.value = (data.features ?? []).slice().sort(
      (a, b) => (a.priority ?? 999) - (b.priority ?? 999),
    )
    error.value = null
  }
  catch (err: unknown) {
    error.value = (err as Error).message
  }
}

export function useFeatures() {
  if (!started) {
    started = true
    usePolling(fetchFeatures, POLL_INTERVAL)
  }
  return { features, error, refresh: fetchFeatures }
}

