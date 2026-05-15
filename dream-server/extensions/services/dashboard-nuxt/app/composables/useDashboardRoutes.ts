// Routen-Registry der Nuxt-Variante. Ersetzt
// `dashboard/src/plugins/{core,registry}.js`.
//
// Konvention:
//   * `to`        - NuxtLink-Ziel (= File-System-Routing-Pfad)
//   * `label`     - Sidebar-Beschriftung (i18n folgt in Phase 5)
//   * `icon`      - Iconify-Name (Lucide via Nuxt UI), z.B. `i-lucide-gauge`
//   * `order`     - numerische Sortierung in der Sidebar
//   * `predicate` - optional: Funktion `(ctx) => boolean`, entscheidet
//                   ob die Route in der Sidebar erscheint. Route ist
//                   immer registriert (NuxtLinks funktionieren), nur
//                   die Sidebar-Anzeige wird gefiltert.
//   * `external`  - true => oeffnet in neuem Tab, kein NuxtLink
//
// Phase 4 wird die Stub-Pages durch echte Pendants ersetzen; die
// Routen-IDs hier bleiben stabil, damit Sidebar/Predicate nicht
// nachgezogen werden muessen.

import type { ComputedRef } from 'vue'
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'

export interface DashboardRoute {
  id: string
  to: string
  label: string
  icon: string
  order: number
  /** Nur in Sidebar zeigen wenn predicate true (oder undefined). */
  predicate?: (ctx: PredicateContext) => boolean
}

export interface PredicateContext {
  serviceIds: string[]
  hasService: (needle: string) => boolean
  gpuCount: number
}

export const coreRoutes: DashboardRoute[] = [
  {
    id: 'dashboard',
    to: '/',
    label: 'Dashboard',
    icon: 'i-lucide-layout-dashboard',
    order: 0,
  },
  {
    id: 'gpu',
    to: '/gpu',
    label: 'GPU Monitor',
    icon: 'i-lucide-activity',
    order: 1,
    // Erst sichtbar wenn mehr als 1 GPU vorhanden (Multi-GPU-Diag).
    predicate: ({ gpuCount }) => gpuCount > 1,
  },
  {
    id: 'extensions',
    to: '/extensions',
    label: 'Extensions',
    icon: 'i-lucide-puzzle',
    order: 2,
  },
  {
    id: 'integrations',
    to: '/extensions/integrations',
    label: 'Integrations',
    icon: 'i-lucide-network',
    order: 2.1,
  },
  {
    id: 'models',
    to: '/models',
    label: 'Models',
    icon: 'i-lucide-box',
    order: 3,
  },
  {
    id: 'projects',
    to: '/projects',
    label: 'Projects',
    icon: 'i-lucide-list-checks',
    order: 4,
    predicate: ({ hasService }) => hasService('vikunja'),
  },
  {
    id: 'invites',
    to: '/invites',
    label: 'Invites',
    icon: 'i-lucide-user-plus',
    order: 4.2,
  },
  {
    id: 'finance-guru',
    to: '/finance-guru',
    label: 'Finance Guru',
    icon: 'i-lucide-trending-up',
    order: 4.5,
    // Sichtbar wenn finance-guru-api ODER lotto-oracle registriert sind.
    predicate: ({ hasService }) =>
      hasService('finance-guru') || hasService('finance guru')
      || hasService('lotto-oracle') || hasService('lotto oracle'),
  },
  {
    id: 'repo-map',
    to: '/repo-map',
    label: 'Repo Map',
    icon: 'i-lucide-git-branch',
    order: 5,
    predicate: ({ hasService }) => hasService('vikunja') && hasService('n8n'),
  },
  {
    id: 'settings',
    to: '/settings',
    label: 'Settings',
    icon: 'i-lucide-settings',
    order: 99,
  },
]

/**
 * Composable: liefert die Sidebar-relevante (gefilterte + sortierte)
 * Routenliste reaktiv. Predicate-Inputs kommen aus useSystemStore,
 * d.h. die Liste aktualisiert sich automatisch sobald das Service-
 * Inventory sich aendert (z.B. nach `dream enable lotto-oracle`).
 */
export function useDashboardRoutes(): {
  routes: ComputedRef<DashboardRoute[]>
  visibleSidebar: ComputedRef<DashboardRoute[]>
} {
  const store = useSystemStore()
  const { status } = storeToRefs(store)

  const ctx = computed<PredicateContext>(() => ({
    serviceIds: store.serviceIds,
    hasService: store.hasService,
    gpuCount: status.value?.gpu?.gpu_count || 1,
  }))

  const routes = computed(() =>
    [...coreRoutes].sort((a, b) => a.order - b.order),
  )

  const visibleSidebar = computed(() =>
    routes.value.filter(r => !r.predicate || r.predicate(ctx.value)),
  )

  return { routes, visibleSidebar }
}

