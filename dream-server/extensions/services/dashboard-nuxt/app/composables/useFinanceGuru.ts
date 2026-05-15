// useFinanceGuru — kapselt /api/finance-guru/* fuer den Strategies-Tab
// (Phase 4 Welle C.1a). Pendant zur in-component-Logik in
// dashboard/src/pages/FinanceGuru.jsx (StrategiesTab).
//
// Modul-cached state, 30 s Polling — analog zu useExtensions/useStatus.

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import { usePolling } from '~/composables/usePolling'
import type {
  FinanceDecideResponse,
  FinanceLedger,
  FinanceSchedule,
  FinanceStatus,
  FinanceStrategiesResponse,
  FinanceStrategy,
  FinanceHistoryExtent,
} from '~/types/api'

const POLL_INTERVAL = 30_000

const status: Ref<FinanceStatus | null> = ref(null)
const strategies: Ref<FinanceStrategy[]> = ref([])
const schedule: Ref<FinanceSchedule | null> = ref(null)
const nextRun: Ref<string | null> = ref(null)
const historyExtent: Ref<FinanceHistoryExtent | null> = ref(null)
const ledgers: Ref<Record<string, FinanceLedger>> = ref({})
const loading = ref(true)
const error: Ref<string | null> = ref(null)

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
    loading,
    error,
    aggregate,
    fetchAll,
    decide,
  }
}

