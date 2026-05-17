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

    // Phase P-5.1: count each verdict bucket separately so the badge
    // can show the WORST severity (driving its colour) plus an honest
    // breakdown in the tooltip. Showing "3" when only 1 is actually
    // an error and 2 are just no-progress (e.g. weekend, no movers)
    // was misleading operators into thinking the stack was on fire.
    const buckets: Record<FinanceWorkflowVerdict, FinanceWorkflowHealthRow[]> = {
      'healthy':     [],
      'no-progress': [],
      'silent-skip': [],
      'errors':      [],
    }
    for (const r of rows) (buckets[r.verdict] ?? buckets['no-progress']).push(r)
    const nErr    = buckets.errors.length
    const nSilent = buckets['silent-skip'].length
    const nNoProg = buckets['no-progress'].length
    const unhealthy = nErr + nSilent + nNoProg

    if (unhealthy === 0) {
      return {
        color: 'success',
        label: 'ok',
        title: `${rows.length} Workflows ok (Fenster ${health.value.window_hours} h)`,
        verdict: 'healthy',
        unhealthy: 0,
      }
    }

    // Helper: short "wf=verdict" comma list, capped at 3 entries.
    const fmt = (list: FinanceWorkflowHealthRow[]) =>
      list.slice(0, 3).map(r => `${r.workflow}=${r.verdict}`).join(', ')
        + (list.length > 3 ? `, +${list.length - 3}` : '')

    // Severity gate drives the colour:
    //   errors      → red, label = nErr        (real failure to act on)
    //   silent-skip → red, label = nSilent     (workflow hiding things)
    //   no-progress → amber, label = nNoProg   (honest "nothing to do")
    // The tooltip always lists every non-healthy row so the operator
    // can decide whether the "no-progress" entries are expected
    // (weekend/off-hours) or a sign of upstream silence.
    if (nErr > 0) {
      const parts: string[] = [`${nErr} error(s)`]
      if (nSilent) parts.push(`${nSilent} silent-skip`)
      if (nNoProg) parts.push(`${nNoProg} no-progress`)
      const offenders = fmt([
        ...buckets.errors,
        ...buckets['silent-skip'],
        ...buckets['no-progress'],
      ])
      return {
        color:   'error',
        label:   String(nErr),
        title:   `${parts.join(' + ')}: ${offenders}`,
        verdict: 'errors',
        unhealthy,
      }
    }
    if (nSilent > 0) {
      const offenders = fmt([
        ...buckets['silent-skip'],
        ...buckets['no-progress'],
      ])
      const suffix = nNoProg ? ` + ${nNoProg} no-progress` : ''
      return {
        color:   'error',
        label:   String(nSilent),
        title:   `${nSilent} silent-skip${suffix}: ${offenders}`,
        verdict: 'silent-skip',
        unhealthy,
      }
    }
    // Only no-progress remains → amber, not red. Operator already
    // knows the workflow is alive; the per-row last_skip_note
    // explains why (e.g. "no news in window", "no movers > 3%/1h").
    return {
      color:   'warning',
      label:   String(nNoProg),
      title:   `${nNoProg} Workflow(s) ohne Fortschritt: ${fmt(buckets['no-progress'])}`,
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

