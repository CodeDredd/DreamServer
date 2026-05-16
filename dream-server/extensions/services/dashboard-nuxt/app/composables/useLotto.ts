// useLotto — kapselt /api/lotto/* fuer den Lotto-Tab im Finance-Guru
// (Phase 4 Welle C.1b). Pendant zur in-component-Logik in
// dashboard/src/pages/LottoTab.jsx (~1011 LoC React).
//
// Polling-Intervall: 60 s (Status + Games-Liste). Detail-Daten
// (draws/tips/stats/strategies/sweet-spot) laden wir nur on-demand
// beim Switch der ausgewaehlten Spielart und nach Mutationen, weil
// jede Detail-Page ~5 parallele Requests sind und die Daten sich
// nur nach dem naechsten Cron-Run aendern.

import { computed, ref, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import { usePolling } from '~/composables/usePolling'
import type {
  LottoActionResponse,
  LottoCustomScheinResponse,
  LottoDraw,
  LottoDrawsResponse,
  LottoGame,
  LottoGamesResponse,
  LottoJackpotBacktestResponse,
  LottoOptimalScheinResponse,
  LottoStats,
  LottoStatus,
  LottoStrategiesResponse,
  LottoStrategyDescriptor,
  LottoSweetSpotResponse,
  LottoTipsResponse,
  LottoTipsRun,
} from '~/types/api'

const POLL_INTERVAL = 60_000

// Modul-Cache fuer Status + Games-Liste (cheap, polled).
const status: Ref<LottoStatus | null> = ref(null)
const games: Ref<LottoGame[]> = ref([])
const overviewLoading = ref(true)
const overviewError: Ref<string | null> = ref(null)
let overviewStarted = false

// Selektion + Detail (nicht modul-cached: gehoert zur Page-Instanz).
// Wird in useLotto() pro Component-Instanz neu angelegt.

export interface BusyState {
  kind: 'refresh' | 'backfill' | 'generate'
}

export interface BusyMsg {
  tone: 'ok' | 'error'
  text: string
}

export function useLotto() {
  const api = useApi()

  const selectedId: Ref<string | null> = ref(null)
  const draws: Ref<LottoDraw[]> = ref([])
  const tipsRun: Ref<LottoTipsRun | null> = ref(null)
  const stats: Ref<LottoStats | null> = ref(null)
  const strategies: Ref<LottoStrategyDescriptor[]> = ref([])
  const sweetSpot: Ref<LottoSweetSpotResponse | null> = ref(null)
  const recencyK = ref(1)
  const activeStrategy: Ref<string | null> = ref(null)
  const busy: Ref<BusyState['kind'] | null> = ref(null)
  const busyMsg: Ref<BusyMsg | null> = ref(null)
  const detailError: Ref<string | null> = ref(null)

  // Per-component flags — nicht modul-shared.
  const userPickedK = ref(false)
  const autoRegen: Ref<{ gameId: string, k: number } | null> = ref(null)

  async function fetchOverview(): Promise<void> {
    try {
      try {
        const sBody = await api.get<LottoStatus>('/api/lotto/status')
        status.value = sBody
        if (!sBody?.available) {
          overviewError.value = sBody?.message || 'lotto-oracle nicht erreichbar'
          overviewLoading.value = false
          return
        }
      }
      catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        overviewError.value = msg
        overviewLoading.value = false
        return
      }

      const gBody = await api.get<LottoGamesResponse>('/api/lotto/games')
      games.value = gBody.games || []
      if (!selectedId.value && games.value.length) {
        selectedId.value = games.value[0]?.id ?? null
      }
      overviewError.value = null
    }
    catch (e: unknown) {
      overviewError.value = e instanceof Error ? e.message : String(e)
    }
    finally {
      overviewLoading.value = false
    }
  }

  async function fetchSelected(gameId: string | null, kForList?: number): Promise<void> {
    if (!gameId) return
    const k = kForList ?? recencyK.value
    try {
      const [drawRes, tipsRes, statsRes, stratRes, sweetRes] = await Promise.allSettled([
        api.get<LottoDrawsResponse>(`/api/lotto/draws?game=${encodeURIComponent(gameId)}&limit=20`),
        api.get<LottoTipsResponse>(`/api/lotto/tips?game=${encodeURIComponent(gameId)}`),
        api.get<LottoStats>(`/api/lotto/stats?game=${encodeURIComponent(gameId)}`),
        api.get<LottoStrategiesResponse>(`/api/lotto/games/${encodeURIComponent(gameId)}/strategies?recency_k=${k}`),
        api.get<LottoSweetSpotResponse>(`/api/lotto/games/${encodeURIComponent(gameId)}/sweet-spot`),
      ])

      draws.value = drawRes.status === 'fulfilled' ? (drawRes.value.draws || []) : []
      const run = tipsRes.status === 'fulfilled' ? (tipsRes.value.run ?? null) : null
      tipsRun.value = run
      stats.value = statsRes.status === 'fulfilled' ? statsRes.value : null
      strategies.value = stratRes.status === 'fulfilled' ? (stratRes.value.strategies || []) : []
      const sweetBody = sweetRes.status === 'fulfilled' ? sweetRes.value : null
      sweetSpot.value = sweetBody

      // Auto-pick K bis User manuell uebernimmt — analog zu React.
      if (!userPickedK.value) {
        const recommended = sweetBody?.recommended_k
        const usedK = run?.params?.recency_k
        const next = typeof recommended === 'number'
          ? recommended
          : typeof usedK === 'number'
            ? usedK
            : 1
        recencyK.value = next
        if (
          typeof recommended === 'number'
          && typeof usedK === 'number'
          && usedK !== recommended
        ) {
          autoRegen.value = { gameId, k: recommended }
        }
      }
      detailError.value = null
    }
    catch (e: unknown) {
      detailError.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function doAction(
    kind: BusyState['kind'],
    opts: { recencyK?: number } = {},
  ): Promise<void> {
    busy.value = kind
    busyMsg.value = null
    try {
      let res: LottoActionResponse | null = null
      const kForRequest = typeof opts.recencyK === 'number' ? opts.recencyK : recencyK.value

      if (kind === 'refresh') {
        res = await api.post<LottoActionResponse>('/api/lotto/refresh', {})
      }
      else if (kind === 'backfill') {
        res = await api.post<LottoActionResponse>('/api/lotto/refresh/full', {})
      }
      else if (kind === 'generate') {
        const body = selectedId.value
          ? { game: selectedId.value, recency_k: kForRequest }
          : { recency_k: kForRequest }
        res = await api.post<LottoActionResponse>('/api/lotto/tips/generate', body)
      }

      busyMsg.value = {
        tone: 'ok',
        text:
          kind === 'backfill'
            ? 'Backfill gestartet — kann 1–3 Minuten dauern.'
            : kind === 'refresh'
              ? 'Inkrementeller Fetch gestartet.'
              : `Neue Tipps generiert (Recency K=${kForRequest}).`,
      }
      void res
      // Nach kurzer Verzoegerung re-poll, damit der Operator das Ergebnis sieht.
      setTimeout(() => {
        void fetchOverview()
        void fetchSelected(selectedId.value)
      }, 1500)
    }
    catch (e: unknown) {
      busyMsg.value = {
        tone: 'error',
        text: e instanceof Error ? e.message : String(e),
      }
    }
    finally {
      busy.value = null
    }
  }

  function handleKChange(newK: number): void {
    if (newK === recencyK.value) return
    userPickedK.value = true
    recencyK.value = newK
    if (selectedId.value) void doAction('generate', { recencyK: newK })
  }

  function selectGame(id: string | null): void {
    if (id === selectedId.value) return
    // Reset Manual-K-Override beim Spielwechsel — jedes Spiel landet
    // bei seinem eigenen empfohlenen K.
    userPickedK.value = false
    selectedId.value = id
    void fetchSelected(id)
  }

  function consumeAutoRegen(): void {
    const pending = autoRegen.value
    if (!pending || pending.gameId !== selectedId.value) return
    if (busy.value) return
    autoRegen.value = null
    void doAction('generate', { recencyK: pending.k })
  }

  // ---------- Jackpot-Backtest (10y) ----------
  const jackpotBacktest: Ref<LottoJackpotBacktestResponse | null> = ref(null)
  const jackpotLoading = ref(false)
  const jackpotError: Ref<string | null> = ref(null)
  async function fetchJackpotBacktest(
    gameId: string | null,
    opts: { years?: number, rows?: number } = {},
  ): Promise<void> {
    if (!gameId) return
    jackpotLoading.value = true
    jackpotError.value = null
    try {
      const years = opts.years ?? 10
      const rows = opts.rows ?? 1
      const q = `years=${years}&rows=${rows}&recency_k=${recencyK.value}`
      jackpotBacktest.value = await api.get<LottoJackpotBacktestResponse>(
        `/api/lotto/games/${encodeURIComponent(gameId)}/jackpot-backtest?${q}`,
      )
    }
    catch (e: unknown) {
      jackpotError.value = e instanceof Error ? e.message : String(e)
      jackpotBacktest.value = null
    }
    finally {
      jackpotLoading.value = false
    }
  }

  // ---------- Optimal-Schein ----------
  const optimalSchein: Ref<LottoOptimalScheinResponse | null> = ref(null)
  const optimalLoading = ref(false)
  const optimalError: Ref<string | null> = ref(null)
  async function fetchOptimalSchein(opts: { recencyK?: number } = {}): Promise<void> {
    optimalLoading.value = true
    optimalError.value = null
    try {
      const k = opts.recencyK ?? recencyK.value
      optimalSchein.value = await api.get<LottoOptimalScheinResponse>(
        `/api/lotto/optimal-schein?recency_k=${k}`,
      )
    }
    catch (e: unknown) {
      optimalError.value = e instanceof Error ? e.message : String(e)
      optimalSchein.value = null
    }
    finally {
      optimalLoading.value = false
    }
  }

  // ---------- Custom-Schein ----------
  async function generateCustomSchein(fields: Array<{
    game: string
    strategy: string | null
    count?: number
    recency_k?: number
  }>): Promise<LottoCustomScheinResponse> {
    const body = { fields: fields.map(f => ({
      game: f.game,
      strategy: f.strategy ?? null,
      count: f.count ?? 1,
      recency_k: f.recency_k ?? recencyK.value,
    })) }
    return await api.post<LottoCustomScheinResponse>(
      '/api/lotto/scheine/generate', body,
    )
  }

  if (!overviewStarted) {
    overviewStarted = true
    usePolling(fetchOverview, POLL_INTERVAL)
  }

  const selectedGame = computed<LottoGame | null>(() =>
    games.value.find(g => g.id === selectedId.value) ?? null,
  )

  return {
    // Modul-shared
    status,
    games,
    overviewLoading,
    overviewError,
    fetchOverview,
    // Per-component selection
    selectedId,
    selectedGame,
    selectGame,
    draws,
    tipsRun,
    stats,
    strategies,
    sweetSpot,
    recencyK,
    activeStrategy,
    busy,
    busyMsg,
    detailError,
    autoRegen,
    fetchSelected,
    doAction,
    handleKChange,
    consumeAutoRegen,
    // Jackpot-Backtest
    jackpotBacktest,
    jackpotLoading,
    jackpotError,
    fetchJackpotBacktest,
    // Optimal-Schein
    optimalSchein,
    optimalLoading,
    optimalError,
    fetchOptimalSchein,
    // Custom-Schein
    generateCustomSchein,
  }
}

