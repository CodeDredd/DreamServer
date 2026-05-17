// useEnrichmentHealth — Phase P-5. Polls /api/finance-guru/enrichment/
// health on a slow cadence (60 s) so the sidebar can render a colour-
// coded badge on the Trading route without coupling to the
// finance-guru page composable. Silently no-ops when finance-guru is
// not installed (404 / network error) — the predicate on the route
// then hides the badge entirely.
//
// Module-scoped cached state + a `started` lock guarantee that even
// with default-layout HMR we only spin up one polling loop per tab.

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import { usePolling } from '~/composables/usePolling'
import type {
  FinanceEnrichmentHealth,
  FinanceWorkflowHealthRow,
  FinanceWorkflowVerdict,
} from '~/types/api'

const POLL_INTERVAL = 60_000
const WINDOW_HOURS = 24

const health: Ref<FinanceEnrichmentHealth | null> = ref(null)
const loading = ref(false)
const lastError: Ref<string | null> = ref(null)
let started = false

// Verdict severity rank: high number = worse. The sidebar badge picks
// the worst row's verdict for its colour. Tie-break by recency would
// be noise; operator just needs a single red/amber/green signal.
const VERDICT_RANK: Record<FinanceWorkflowVerdict, number> = {
  'healthy':     0,
  'no-progress': 1,
  'silent-skip': 2,
  'errors':      3,
}

export interface EnrichmentBadge {
  /** Nuxt UI badge color token. */
  color: 'success' | 'warning' | 'error' | 'neutral'
  /** Short label rendered in the sidebar. */
  label: string
  /** Hover-tooltip explanation with worst offenders. */
  title: string
  verdict: FinanceWorkflowVerdict | 'unknown'
  /** Number of workflows with verdict !== healthy. */
  unhealthy: number
}

export function useEnrichmentHealth() {
  const api = useApi()

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      const data = await api.get<FinanceEnrichmentHealth>(
        `/api/finance-guru/enrichment/health?window_hours=${WINDOW_HOURS}`,
      )
      health.value = data
      lastError.value = null
    }
    catch (err: unknown) {
      // finance-guru-api may not be installed — that's a *valid* state
      // (sidebar simply renders no badge). Don't spam errors.
      health.value = null
      lastError.value = err instanceof Error ? err.message : String(err)
    }
    finally {
      loading.value = false
    }
  }

  function start(): void {
    if (started || typeof window === 'undefined') return
    started = true
    void refresh()
    usePolling(refresh, POLL_INTERVAL)
  }

  const worstVerdict: ComputedRef<FinanceWorkflowVerdict | 'unknown'> = computed(() => {
    const rows = health.value?.workflows ?? []
    if (!rows.length) return 'unknown'
    let worst: FinanceWorkflowVerdict = 'healthy'
    for (const r of rows) {
      if ((VERDICT_RANK[r.verdict] ?? 0) > (VERDICT_RANK[worst] ?? 0)) {
        worst = r.verdict
      }
    }
    return worst
  })

  const unhealthyRows: ComputedRef<FinanceWorkflowHealthRow[]> = computed(() =>
    (health.value?.workflows ?? []).filter(r => r.verdict !== 'healthy'),
  )

  const badge: ComputedRef<EnrichmentBadge | null> = computed(() => {
    // No data at all → hide. (finance-guru not installed, or first
    // poll still in flight.)
    if (!health.value) return null
    const rows = health.value.workflows ?? []
    if (!rows.length) return null

    const w = worstVerdict.value
    const unhealthy = unhealthyRows.value.length
    if (w === 'healthy') {
      return {
        color: 'success',
        label: 'ok',
        title: `${rows.length} Workflows ok (Fenster ${health.value.window_hours} h)`,
        verdict: 'healthy',
        unhealthy: 0,
      }
    }
    const worstNames = unhealthyRows.value.slice(0, 3)
      .map(r => `${r.workflow}=${r.verdict}`).join(', ')
    const more = unhealthy > 3 ? `, +${unhealthy - 3}` : ''
    if (w === 'errors') {
      return {
        color: 'error',
        label: String(unhealthy),
        title: `Errors in ${unhealthy} Workflow(s): ${worstNames}${more}`,
        verdict: 'errors',
        unhealthy,
      }
    }
    if (w === 'silent-skip') {
      return {
        color: 'error',
        label: String(unhealthy),
        title: `Silent skips in ${unhealthy} Workflow(s): ${worstNames}${more}`,
        verdict: 'silent-skip',
        unhealthy,
      }
    }
    // no-progress (workflow ran but produced 0 ok rows in window)
    return {
      color: 'warning',
      label: String(unhealthy),
      title: `Kein Fortschritt in ${unhealthy} Workflow(s): ${worstNames}${more}`,
      verdict: 'no-progress',
      unhealthy,
    }
  })

  return {
    health,
    loading,
    lastError,
    worstVerdict,
    unhealthyRows,
    badge,
    start,
    refresh,
  }
}


