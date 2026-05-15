// First-Run-Middleware (Phase 4 Welle D). Pendant zur Routing-Logik in
// dashboard/src/App.jsx (~Z. 39–80), die bei firstRun=true die normale
// App-Shell durch <FirstBoot/> ersetzt.
//
// Strategie:
//   * Setup-Status laden (Pinia-Store ist serverseitig authoritative).
//   * Wenn firstRun=true und nicht schon auf /first-boot -> redirect.
//   * Wenn firstRun=false und auf /first-boot -> redirect zu /.
//
// SSR ist im Dashboard-Nuxt deaktiviert (`ssr: false`), Middleware
// laeuft also nur clientseitig — wir koennen safe auf den Store
// zugreifen ohne Hydration-Mismatch zu riskieren.

import { useSetupStore } from '~/stores/setup'

export default defineNuxtRouteMiddleware(async (to) => {
  const store = useSetupStore()
  // Lazy-laden: Store hat in initial state firstRun=false, damit der
  // Wizard nicht bei API-Hickups irrtuemlich aufpoppt (siehe Doku in
  // useFirstRun.ts). Beim ersten Aufruf kennt er den echten Status
  // noch nicht — also einmal blockierend nachladen.
  if (!store.raw) {
    await store.refresh()
  }

  const onWizard = to.path === '/first-boot'

  if (store.firstRun && !onWizard) {
    return navigateTo('/first-boot', { replace: true })
  }
  if (!store.firstRun && onWizard) {
    return navigateTo('/', { replace: true })
  }
})

