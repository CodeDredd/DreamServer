// PWA-Install-Prompt — VueUse-basiert. Ersetzt den manuellen
// Listener-Tanz aus `dashboard/src/hooks/usePwaInstallPrompt.js`.
// Nuxt-PWA + Workbox läuft schon; das hier ist nur die User-Geste.

import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useStorage } from '@vueuse/core'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

const VISIT_COUNT_KEY = 'dream-visit-count'
const DISMISSED_KEY = 'dream-pwa-dismissed-at'
const ENGAGEMENT_THRESHOLD = 3

export function usePwaInstall() {
  const deferred = ref<BeforeInstallPromptEvent | null>(null)
  const visitCount = useStorage<number>(VISIT_COUNT_KEY, 0)
  const dismissedAt = useStorage<number>(DISMISSED_KEY, 0)

  // Engagement: erst nach N Besuchen anbieten — Spam-Schutz.
  const isEligible = computed(() => visitCount.value >= ENGAGEMENT_THRESHOLD)

  // Standalone? Dann hat der User schon installiert — kein Prompt nötig.
  const isStandalone = computed(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia?.('(display-mode: standalone)').matches
      || (window.navigator as { standalone?: boolean }).standalone === true
  })

  const canInstall = computed(() =>
    !isStandalone.value && deferred.value !== null && isEligible.value && dismissedAt.value === 0,
  )

  function handler(ev: Event) {
    ev.preventDefault()
    deferred.value = ev as BeforeInstallPromptEvent
  }

  async function promptInstall() {
    if (!deferred.value) return null
    await deferred.value.prompt()
    const choice = await deferred.value.userChoice
    if (choice.outcome === 'dismissed') {
      dismissedAt.value = Date.now()
    }
    deferred.value = null
    return choice.outcome
  }

  function dismiss() {
    dismissedAt.value = Date.now()
    deferred.value = null
  }

  onMounted(() => {
    visitCount.value = (visitCount.value ?? 0) + 1
    window.addEventListener('beforeinstallprompt', handler)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('beforeinstallprompt', handler)
  })

  return {
    canInstall,
    isStandalone,
    isEligible,
    visitCount,
    promptInstall,
    dismiss,
  }
}

