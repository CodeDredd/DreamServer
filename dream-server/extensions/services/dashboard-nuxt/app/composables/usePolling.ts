// Visibility-aware Polling-Helper.
//
// Replikt das in den React-Hooks etablierte Verhalten:
//   * pausiert bei `document.hidden = true` (außer der erste Tick),
//   * überlappende Requests werden geskippt (`fetchInFlight`),
//   * resumed sofort beim `visibilitychange`,
//   * stoppt sauber on-unmount.
//
// Verwendung:
//   const { stop, refresh } = usePolling(load, 5000)

import { onScopeDispose } from 'vue'
import { useDocumentVisibility, useEventListener } from '@vueuse/core'

export interface PollingHandle {
  /** Force a fetch right now (bypasses the in-flight lock). */
  refresh: () => Promise<void>
  /** Stop the timer and remove visibility listener. */
  stop: () => void
}

export interface PollingOptions {
  /** Run the first tick even if the tab is hidden. Default: true. */
  immediate?: boolean
  /** Re-enable polling when the tab becomes visible again. Default: true. */
  resumeOnVisible?: boolean
}

export function usePolling(
  task: () => Promise<unknown> | unknown,
  intervalMs: number,
  opts: PollingOptions = {},
): PollingHandle {
  const visibility = useDocumentVisibility()
  const inFlight = ref(false)
  const hasInitial = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  const tick = async (force = false) => {
    if (!force && visibility.value === 'hidden' && hasInitial.value) return
    if (inFlight.value) return
    inFlight.value = true
    try {
      await task()
      hasInitial.value = true
    }
    finally {
      inFlight.value = false
    }
  }

  // Initial fetch — also runs on hidden tabs so first paint is never
  // permanently stuck on a loading skeleton (multi-monitor / restored
  // session). After that, the hidden-tab guard kicks in for subsequent
  // ticks to save CPU/network.
  if (opts.immediate !== false) {
    void tick(true)
  }

  timer = setInterval(() => { void tick(false) }, intervalMs)

  if (opts.resumeOnVisible !== false) {
    useEventListener(document, 'visibilitychange', () => {
      if (visibility.value === 'visible') void tick(true)
    })
  }

  const stop = () => {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  // Auto-cleanup when the consumer component / pinia store gets disposed.
  onScopeDispose(stop)

  return {
    refresh: () => tick(true),
    stop,
  }
}

