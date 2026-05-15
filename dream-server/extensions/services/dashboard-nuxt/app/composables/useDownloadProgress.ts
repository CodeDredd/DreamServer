// `/api/models/download-status` — adaptives Polling-Intervall.
// 1 s während eines aktiven Downloads, 10 s im Idle.

import { computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useDownloadsStore, formatBytes, formatEta } from '~/stores/downloads'
import { usePolling } from '~/composables/usePolling'

const INTERVAL_ACTIVE = 1000
const INTERVAL_IDLE = 10_000

let started = false
let activeTimer: { stop: () => void, refresh: () => Promise<void> } | null = null
let idleTimer: { stop: () => void, refresh: () => Promise<void> } | null = null

export function useDownloadProgress() {
  const store = useDownloadsStore()

  if (!started) {
    started = true
    // Initial idle-poll. Wir wechseln Mode beim ersten Statuswechsel.
    idleTimer = usePolling(() => store.refresh(), INTERVAL_IDLE)
  }

  // Mode-Switch beim Übergang isDownloading → true / false.
  watch(() => store.isDownloading, (active) => {
    if (active && !activeTimer) {
      idleTimer?.stop()
      idleTimer = null
      activeTimer = usePolling(() => store.refresh(), INTERVAL_ACTIVE)
    }
    else if (!active && !idleTimer) {
      activeTimer?.stop()
      activeTimer = null
      idleTimer = usePolling(() => store.refresh(), INTERVAL_IDLE)
    }
  })

  const { isDownloading, progress, error } = storeToRefs(store)

  return {
    isDownloading,
    progress,
    error,
    formatBytes,
    formatEta,
    refresh: () => store.refresh(),
    cancelDownload: () => store.cancel(),
    /** Convenience für UI-Karten. */
    percentLabel: computed(() => progress.value
      ? `${progress.value.percent.toFixed(1)} %`
      : '—'),
  }
}

