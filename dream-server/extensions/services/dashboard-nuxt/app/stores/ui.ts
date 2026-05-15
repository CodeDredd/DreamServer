// Reines UI-State (kein Backend). Persistiert in `localStorage` /
// `sessionStorage` über VueUse — mit identischen Storage-Keys wie die
// React-Variante, damit ein Browser, der Token-Cookie + Splash-Flag
// schon hat, nach dem Cutover keine Re-Onboarding-Schleife sieht.

import { defineStore } from 'pinia'
import { useStorage, useSessionStorage } from '@vueuse/core'

export const useUiStore = defineStore('ui', () => {
  // localStorage — überlebt Tab-Schließen.
  const sidebarCollapsed = useStorage('dream-sidebar-collapsed', false)

  // sessionStorage — Splash genau einmal pro Browser-Session zeigen,
  // nicht bei jedem F5 / neuem Tab.
  const splashShown = useSessionStorage('dream-splash-shown', false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function markSplashShown() {
    splashShown.value = true
  }

  return {
    sidebarCollapsed,
    splashShown,
    toggleSidebar,
    markSplashShown,
  }
})

