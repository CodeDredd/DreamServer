// `/api/services/resources` — per-Container CPU/Mem/Disk Stats.
// Polling 10 s wie React-Pendant (`Dashboard.jsx` Zeile 533-554).
// Bewusst KEIN ORM-Mirror: das sind ephemere Metriken (jede Pollung
// ueberschreibt den Wert komplett), nicht relationale Stammdaten.
// Components lesen direkt aus `resources` ref + `byServiceId`-Map.

import { computed, ref, type Ref } from 'vue'
import type { ServiceResourceEntry, ServiceResourcesResponse } from '~/types/api'
import { dreamFetch } from '~/composables/useApi'
import { usePolling } from '~/composables/usePolling'

const POLL_INTERVAL = 10_000

const resources: Ref<ServiceResourceEntry[]> = ref([])
const error: Ref<string | null> = ref(null)
let started = false

async function fetchResources() {
  try {
    const data = await dreamFetch<ServiceResourcesResponse>('/api/services/resources')
    resources.value = data.services ?? []
    error.value = null
  }
  catch (err: unknown) {
    error.value = (err as Error).message
  }
}

export function useServiceResources() {
  if (!started) {
    started = true
    usePolling(fetchResources, POLL_INTERVAL)
  }
  const byServiceId = computed(() => {
    const map = new Map<string, ServiceResourceEntry>()
    for (const r of resources.value) map.set(r.id, r)
    return map
  })
  return { resources, byServiceId, error, refresh: fetchResources }
}



