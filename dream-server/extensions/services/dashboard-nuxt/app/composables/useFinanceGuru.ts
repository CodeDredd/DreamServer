// useFinanceGuru — kapselt /api/finance-guru/* fuer den Strategies-Tab
// (Phase 4 Welle C.1a). Pendant zur in-component-Logik in
// dashboard/src/pages/FinanceGuru.jsx (StrategiesTab).
//
// Modul-cached state, 30 s Polling — analog zu useExtensions/useStatus.

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import { usePolling } from '~/composables/usePolling'
import type {
  FinanceAnalysesSearchResponse,
  FinanceAuditRow,
  FinanceAuditsResponse,
  FinanceCycleRow,
  FinanceCycleSummary,
  FinanceCyclesResponse,
  FinanceDecideResponse,
  FinanceDslCatalog,
  FinanceEnrichmentRun,
  FinanceEquityPoint,
  FinanceEquityResponse,
  FinanceHistoryExtent,
  FinanceLeaderboardResponse,
  FinanceLeaderboardRow,
  FinanceLedger,
  FinanceLessonsSearchResponse,
  FinanceLifecycleResponse,
  FinanceLifecycleRow,
  FinanceRelationsSearchResponse,
  FinanceSchedule,
  FinanceStatus,
  FinanceStrategiesResponse,
  FinanceStrategy,
} from '~/types/api'

const POLL_INTERVAL = 30_000
const EQUITY_DAYS = 30
const CYCLE_LIMIT = 60
const ENRICHMENT_RUNS_LIMIT = 50

const status: Ref<FinanceStatus | null> = ref(null)
const strategies: Ref<FinanceStrategy[]> = ref([])
const schedule: Ref<FinanceSchedule | null> = ref(null)
const nextRun: Ref<string | null> = ref(null)
const historyExtent: Ref<FinanceHistoryExtent | null> = ref(null)
const ledgers: Ref<Record<string, FinanceLedger>> = ref({})
const cycleSummary: Ref<FinanceCycleSummary | null> = ref(null)
const cycles: Ref<FinanceCycleRow[]> = ref([])
const equity: Ref<Record<string, FinanceEquityPoint[]>> = ref({})
const enrichmentRuns: Ref<FinanceEnrichmentRun[]> = ref([])
const loading = ref(true)
const error: Ref<string | null> = ref(null)

// Phase C/D/E lifecycle + leaderboard. Polled together with the rest.
const lifecycle: Ref<FinanceLifecycleRow[]> = ref([])
const leaderboard: Ref<FinanceLeaderboardRow[]> = ref([])
const leaderboardMeta: Ref<{ window_days: number, target_pct: number } | null> = ref(null)
const dslCatalog: Ref<FinanceDslCatalog | null> = ref(null)

let started = false

export interface FinanceAggregate {
  seeded: number
  equity: number
  realised: number
  trades: number
  positions: number
  totalPnlPct: number
}

export function useFinanceGuru() {
  const api = useApi()

  async function fetchAll() {
    try {
      // Status zuerst — billig, sagt uns ob Upstream erreichbar ist.
      try {
        status.value = await api.get<FinanceStatus>('/api/finance-guru/status')
      }
      catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        status.value = { available: false, message: msg }
      }
      if (!status.value?.available) {
        error.value = status.value?.message || 'finance-guru-api not reachable'
        loading.value = false
        return
      }

      const stratBody = await api.get<FinanceStrategiesResponse>('/api/finance-guru/strategies')
      const list = stratBody.strategies || []
      strategies.value = list
      schedule.value = stratBody.schedule || null
      nextRun.value = stratBody.next_run ?? null
      historyExtent.value = stratBody.history_extent ?? null

      // Alle Ledger parallel — kleine Payloads, ein Request pro Strategie.
      const entries = await Promise.all(
        list.map(async (s) => {
          try {
            const ledger = await api.get<FinanceLedger>(
              `/api/finance-guru/ledger?strategy=${encodeURIComponent(s.name)}`,
            )
            return [s.name, ledger] as const
          }
          catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e)
            return [s.name, { error: msg }] as const
          }
        }),
      )
      ledgers.value = Object.fromEntries(entries)

      // Equity history per strategy (parallel small payloads).
      const equityEntries = await Promise.all(
        list.map(async (s) => {
          try {
            const res = await api.get<FinanceEquityResponse>(
              `/api/finance-guru/equity-history?strategy=${encodeURIComponent(s.name)}&days=${EQUITY_DAYS}`,
            )
            return [s.name, res.points || []] as const
          }
          catch {
            return [s.name, []] as const
          }
        }),
      )
      equity.value = Object.fromEntries(equityEntries)

      // Global cycle log (across all strategies; UI may filter).
      try {
        const cy = await api.get<FinanceCyclesResponse>(
          `/api/finance-guru/cycles?limit=${CYCLE_LIMIT}`,
        )
        cycles.value = cy.cycles || []
        cycleSummary.value = cy.summary || null
        nextRun.value = cy.next_run ?? nextRun.value
      }
      catch {
        // Older finance-guru-api builds may not expose /cycles yet.
        cycles.value = []
        cycleSummary.value = null
      }

      try {
        const enr = await api.get<{ runs: FinanceEnrichmentRun[] }>(
          `/api/finance-guru/enrichment/runs?limit=${ENRICHMENT_RUNS_LIMIT}`,
        )
        enrichmentRuns.value = enr.runs || []
      }
      catch {
        enrichmentRuns.value = []
      }

      // Phase C/D/E: lifecycle index + 7d leaderboard + DSL catalog.
      // All three are small JSON, failures here must not blank the page.
      try {
        const lc = await api.get<FinanceLifecycleResponse>(
          '/api/finance-guru/lifecycle?limit=200',
        )
        lifecycle.value = lc.strategies || []
      }
      catch {
        lifecycle.value = []
      }
      try {
        const lb = await api.get<FinanceLeaderboardResponse>(
          '/api/finance-guru/leaderboard?window=7&limit=50',
        )
        leaderboard.value = lb.rows || []
        leaderboardMeta.value = {
          window_days: lb.window_days, target_pct: lb.target_pct,
        }
      }
      catch {
        leaderboard.value = []
        leaderboardMeta.value = null
      }
      try {
        dslCatalog.value = await api.get<FinanceDslCatalog>(
          '/api/finance-guru/dsl/catalog',
        )
      }
      catch {
        // Older finance-guru-api without Phase D — leave catalog null.
        dslCatalog.value = null
      }

      error.value = null
    }
    catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    finally {
      loading.value = false
    }
  }

  async function decide(strategyName: string | null = null): Promise<FinanceDecideResponse> {
    const body = strategyName ? { strategy: strategyName } : {}
    const res = await api.post<FinanceDecideResponse>('/api/finance-guru/decide', body)
    // Re-poll a few seconds later so the user sees the cycle results.
    setTimeout(() => { void fetchAll() }, 3000)
    return res
  }

  // ----- Phase F: ad-hoc queries (no polling, called on demand) -----------

  async function listAudits(strategy?: string | null, limit = 50): Promise<FinanceAuditRow[]> {
    const qs = new URLSearchParams({ limit: String(limit) })
    if (strategy) qs.set('strategy', strategy)
    try {
      const res = await api.get<FinanceAuditsResponse>(
        `/api/finance-guru/audits?${qs.toString()}`,
      )
      return res.audits || []
    }
    catch { return [] }
  }

  async function searchRelations(query: string, limit = 8, minConfidence = 0.3) {
    if (!query.trim()) return []
    try {
      const res = await api.post<FinanceRelationsSearchResponse>(
        '/api/finance-guru/rag/relations/search',
        { query, limit, min_confidence: minConfidence },
      )
      return res.hits || []
    }
    catch { return [] }
  }

  async function searchLessons(query: string, limit = 8) {
    if (!query.trim()) return []
    try {
      const res = await api.post<FinanceLessonsSearchResponse>(
        '/api/finance-guru/rag/strategy-lessons/search',
        { query, limit },
      )
      return res.hits || []
    }
    catch { return [] }
  }

  async function searchAnalyses(query: string, limit = 8, minConfidence = 0.3) {
    if (!query.trim()) return []
    try {
      const res = await api.post<FinanceAnalysesSearchResponse>(
        '/api/finance-guru/enrichment/asset-analysis/search',
        { query, limit, min_confidence: minConfidence },
      )
      return res.hits || []
    }
    catch { return [] }
  }

  if (!started) {
    started = true
    usePolling(fetchAll, POLL_INTERVAL)
  }

  const aggregate: ComputedRef<FinanceAggregate | null> = computed(() => {
    const kpis = strategies.value
      .map(s => ledgers.value[s.name]?.kpi)
      .filter((k): k is NonNullable<typeof k> => Boolean(k))
    if (!kpis.length) return null
    const seeded = kpis.reduce((sum, k) => sum + (k.seeded_eur || 0), 0)
    const equity = kpis.reduce((sum, k) => sum + (k.equity_eur || 0), 0)
    const realised = kpis.reduce((sum, k) => sum + (k.realised_pnl_eur || 0), 0)
    const trades = kpis.reduce((sum, k) => sum + (k.n_trades || 0), 0)
    const positions = kpis.reduce((sum, k) => sum + (k.n_positions || 0), 0)
    const totalPnlPct = seeded > 0 ? ((equity - seeded) / seeded) * 100 : 0
    return { seeded, equity, realised, trades, positions, totalPnlPct }
  })

  return {
    status,
    strategies,
    schedule,
    nextRun,
    historyExtent,
    ledgers,
    cycles,
    cycleSummary,
    equity,
    enrichmentRuns,
    lifecycle,
    leaderboard,
    leaderboardMeta,
    dslCatalog,
    loading,
    error,
    aggregate,
    fetchAll,
    decide,
    listAudits,
    searchRelations,
    searchLessons,
    searchAnalyses,
  }
}

