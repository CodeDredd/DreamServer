<!--
  Finance-Guru Strategies Tab (Phase 4 Welle C.1a). Pendant zu
  dashboard/src/pages/FinanceGuru.jsx -> StrategiesTab + StrategyDetail
  + KpiCard + Stat (~430 LoC kombiniert). Talkst exklusiv zu
  /api/finance-guru/* via useFinanceGuru.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useFinanceGuru } from '~/composables/useFinanceGuru'
import {
  formatEur,
  formatPct,
  pnlToneClass,
  relTime,
} from '~/utils/format'
import type { FinanceLedger, FinanceStrategy } from '~/types/api'

const WEEKLY_TARGET_PCT = 10

const fg = useFinanceGuru()

const decideLoading = ref(false)
const decideMsg = ref<{ tone: 'ok' | 'error', text: string } | null>(null)
const selectedName = ref<string | null>(null)

// Pre-select erste Strategie sobald geladen.
watch(fg.strategies, (list) => {
  if (!selectedName.value && list.length) {
    selectedName.value = list[0]?.name ?? null
  }
}, { immediate: true })

const selectedStrategy = computed<FinanceStrategy | null>(() =>
  fg.strategies.value.find(s => s.name === selectedName.value) ?? null,
)
const selectedLedger = computed<FinanceLedger | null>(() =>
  selectedName.value ? (fg.ledgers.value[selectedName.value] ?? null) : null,
)

async function runDecide(strategyName: string | null = null) {
  decideLoading.value = true
  decideMsg.value = null
  try {
    const res = await fg.decide(strategyName)
    decideMsg.value = {
      tone: 'ok',
      text: `Queued: ${res.queued_for || 'all-enabled'}`,
    }
  }
  catch (e: unknown) {
    decideMsg.value = {
      tone: 'error',
      text: e instanceof Error ? e.message : String(e),
    }
  }
  finally {
    decideLoading.value = false
  }
}

function pnlOf(name: string): number | undefined {
  return fg.ledgers.value[name]?.kpi?.total_pnl_pct
}

function tradePnlPct(p: { qty: number, avg_price: number, mark_price: number }): number {
  return p.avg_price > 0 ? ((p.mark_price - p.avg_price) / p.avg_price) * 100 : 0
}

function tradePnl(p: { qty: number, avg_price: number, mark_price: number }): number {
  return (p.mark_price - p.avg_price) * p.qty
}
</script>

<template>
  <div class="space-y-6 p-6">
    <!-- Header -->
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="flex items-center gap-2 text-2xl font-bold text-default">
          <UIcon name="i-lucide-trending-up" class="size-6 text-primary" />
          Finance Guru
        </h2>
        <p class="mt-1 text-muted">
          Paper-trade strategy engine — €1000 seed per strategy, 10 %/week target.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          color="neutral"
          variant="ghost"
          icon="i-lucide-refresh-cw"
          square
          title="Refresh"
          @click="fg.fetchAll()"
        />
        <UButton
          color="primary"
          :icon="decideLoading ? 'i-lucide-loader-2' : 'i-lucide-play'"
          :loading="decideLoading"
          :disabled="decideLoading || !fg.status.value?.available"
          title="Run one decision cycle for every enabled strategy"
          @click="runDecide(null)"
        >
          Run decide cycle
        </UButton>
      </div>
    </div>

    <!-- Errors / banners -->
    <UAlert
      v-if="fg.error.value"
      color="error"
      variant="subtle"
      icon="i-lucide-alert-circle"
      title="finance-guru-api not reachable"
    >
      <template #description>
        <p>{{ fg.error.value }}</p>
        <p class="mt-1 text-xs text-muted">
          Check
          <code class="font-mono">dream status finance-guru-api</code>
          on the host.
        </p>
      </template>
    </UAlert>
    <UAlert
      v-if="decideMsg"
      :color="decideMsg.tone === 'ok' ? 'success' : 'error'"
      variant="subtle"
      :title="decideMsg.text"
      :close="{ onClick: () => (decideMsg = null) }"
    />

    <!-- Loading skeleton -->
    <div v-if="fg.loading.value && !fg.strategies.value.length" class="space-y-6">
      <USkeleton class="h-8 w-1/3" />
      <USkeleton class="h-32 rounded-xl" />
      <USkeleton class="h-64 rounded-xl" />
    </div>

    <!-- Aggregate KPI strip -->
    <div v-if="fg.aggregate.value" class="grid grid-cols-2 gap-4 md:grid-cols-5">
      <UCard>
        <div class="flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-wallet" class="size-3.5" /> Total seeded
        </div>
        <div class="text-xl font-semibold text-default">
          {{ formatEur(fg.aggregate.value.seeded) }}
        </div>
        <div class="text-xs text-muted">
          {{ fg.strategies.value.length }} strategies
        </div>
      </UCard>
      <UCard>
        <div class="flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-wallet" class="size-3.5" /> Equity
        </div>
        <div
          class="text-xl font-semibold"
          :class="fg.aggregate.value.totalPnlPct >= 0 ? 'text-success' : 'text-error'"
        >
          {{ formatEur(fg.aggregate.value.equity) }}
        </div>
        <div class="text-xs text-muted">
          {{ formatPct(fg.aggregate.value.totalPnlPct) }}
        </div>
      </UCard>
      <UCard>
        <div class="flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-target" class="size-3.5" /> Vs 10 %/wk target
        </div>
        <div
          class="text-xl font-semibold"
          :class="fg.aggregate.value.totalPnlPct >= WEEKLY_TARGET_PCT ? 'text-success' : 'text-error'"
        >
          {{ formatPct(fg.aggregate.value.totalPnlPct - WEEKLY_TARGET_PCT) }}
        </div>
        <div class="text-xs text-muted">
          target {{ WEEKLY_TARGET_PCT }}%
        </div>
      </UCard>
      <UCard>
        <div class="flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-activity" class="size-3.5" /> Realised PnL
        </div>
        <div
          class="text-xl font-semibold"
          :class="fg.aggregate.value.realised >= 0 ? 'text-success' : 'text-error'"
        >
          {{ formatEur(fg.aggregate.value.realised) }}
        </div>
        <div class="text-xs text-muted">
          {{ fg.aggregate.value.trades }} trades
        </div>
      </UCard>
      <UCard>
        <div class="flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-trending-up" class="size-3.5" /> Open positions
        </div>
        <div class="text-xl font-semibold text-default">
          {{ fg.aggregate.value.positions }}
        </div>
        <div class="text-xs text-muted">
          <template v-if="fg.schedule.value?.cron">
            next {{ relTime(fg.nextRun.value) }} ({{ fg.schedule.value.cron }})
          </template>
          <template v-else>
            no schedule
          </template>
        </div>
      </UCard>
    </div>

    <!-- Strategy list (left) + detail (right) -->
    <div class="grid gap-6 lg:grid-cols-3">
      <div class="space-y-3 lg:col-span-1">
        <h3 class="text-sm font-semibold uppercase tracking-wider text-muted">
          Strategies
        </h3>
        <button
          v-for="s in fg.strategies.value"
          :key="s.name"
          type="button"
          class="w-full rounded-xl border bg-elevated p-4 text-left transition-colors"
          :class="s.name === selectedName
            ? 'border-primary'
            : 'border-default hover:border-primary/50'"
          @click="selectedName = s.name"
        >
          <div class="mb-2 flex items-start justify-between gap-3">
            <div>
              <div class="font-mono text-sm text-default">
                {{ s.name }}
              </div>
              <div class="mt-0.5 text-xs text-muted">
                {{ s.asset_types?.join(' · ') || '' }}
              </div>
            </div>
            <span class="text-sm font-semibold" :class="pnlToneClass(pnlOf(s.name))">
              {{ formatPct(pnlOf(s.name)) }}
            </span>
          </div>
          <div class="flex items-center gap-3 text-xs text-muted">
            <span>{{ formatEur(fg.ledgers.value[s.name]?.kpi?.equity_eur) }}</span>
            <span>· {{ fg.ledgers.value[s.name]?.kpi?.n_positions ?? 0 }} pos</span>
            <span>· {{ fg.ledgers.value[s.name]?.kpi?.n_trades ?? 0 }} trades</span>
            <span v-if="!s.enabled" class="ml-auto uppercase tracking-wider text-warning">
              disabled
            </span>
          </div>
        </button>
      </div>

      <div class="lg:col-span-2">
        <div
          v-if="!selectedStrategy || !selectedLedger"
          class="rounded-xl border border-default bg-elevated p-8 text-center text-muted"
        >
          {{ fg.strategies.value.length ? 'Select a strategy' : 'No strategies registered' }}
        </div>
        <div v-else class="space-y-6">
          <!-- Strategy header card -->
          <UCard>
            <template #header>
              <div class="flex items-start justify-between gap-4">
                <div>
                  <h3 class="font-mono text-lg font-semibold text-default">
                    {{ selectedStrategy.name }}
                  </h3>
                  <p class="mt-1 text-sm text-muted">
                    {{ selectedStrategy.description }}
                  </p>
                </div>
                <UButton
                  color="neutral"
                  variant="outline"
                  size="xs"
                  :icon="decideLoading ? 'i-lucide-loader-2' : 'i-lucide-play'"
                  :loading="decideLoading"
                  :disabled="decideLoading"
                  @click="runDecide(selectedStrategy.name)"
                >
                  Decide now
                </UButton>
              </div>
            </template>

            <div class="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div>
                <div class="text-xs uppercase tracking-wider text-muted">
                  Cash
                </div>
                <div class="mt-0.5 text-base font-semibold text-default">
                  {{ formatEur(selectedLedger.kpi?.cash_eur) }}
                </div>
              </div>
              <div>
                <div class="text-xs uppercase tracking-wider text-muted">
                  Holdings
                </div>
                <div class="mt-0.5 text-base font-semibold text-default">
                  {{ formatEur(selectedLedger.kpi?.holdings_eur) }}
                </div>
              </div>
              <div>
                <div class="text-xs uppercase tracking-wider text-muted">
                  Equity
                </div>
                <div class="mt-0.5 text-base font-semibold text-default">
                  {{ formatEur(selectedLedger.kpi?.equity_eur) }}
                </div>
              </div>
              <div>
                <div class="text-xs uppercase tracking-wider text-muted">
                  PnL
                </div>
                <div
                  class="mt-0.5 text-base font-semibold"
                  :class="pnlToneClass(selectedLedger.kpi?.total_pnl_pct)"
                >
                  {{ formatPct(selectedLedger.kpi?.total_pnl_pct) }}
                </div>
              </div>
            </div>

            <template #footer>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                <span class="flex items-center gap-1">
                  <UIcon name="i-lucide-clock" class="size-3" />
                  last cycle {{ relTime(selectedStrategy.last_ts) }}
                </span>
                <span>signals: {{ selectedStrategy.last_signals ?? 0 }}</span>
                <span>executed: {{ selectedStrategy.last_executed ?? 0 }}</span>
                <span>skipped: {{ selectedStrategy.last_skipped ?? 0 }}</span>
                <span>
                  max position: {{ ((selectedStrategy.max_position_frac || 0) * 100).toFixed(0) }}%
                </span>
              </div>
            </template>
          </UCard>

          <!-- Open positions -->
          <UCard :ui="{ body: 'p-0' }">
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon name="i-lucide-wallet" class="size-3.5 text-muted" />
                <h4 class="text-sm font-semibold">
                  Open positions ({{ selectedLedger.positions?.length ?? 0 }})
                </h4>
              </div>
            </template>
            <div v-if="!selectedLedger.positions?.length" class="px-5 py-6 text-sm text-muted">
              No open positions. Strategy is sitting in cash.
            </div>
            <table v-else class="w-full text-sm">
              <thead class="bg-elevated/50">
                <tr class="text-xs uppercase tracking-wider text-muted">
                  <th class="px-5 py-2 text-left font-medium">
                    Symbol
                  </th>
                  <th class="px-3 py-2 text-right font-medium">
                    Qty
                  </th>
                  <th class="px-3 py-2 text-right font-medium">
                    Avg
                  </th>
                  <th class="px-3 py-2 text-right font-medium">
                    Mark
                  </th>
                  <th class="px-5 py-2 text-right font-medium">
                    PnL
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="p in selectedLedger.positions"
                  :key="p.symbol"
                  class="border-t border-default"
                >
                  <td class="px-5 py-2 font-mono text-default">
                    {{ p.symbol }}
                  </td>
                  <td class="px-3 py-2 text-right">
                    {{ p.qty?.toFixed?.(4) ?? p.qty }}
                  </td>
                  <td class="px-3 py-2 text-right">
                    {{ formatEur(p.avg_price) }}
                  </td>
                  <td class="px-3 py-2 text-right">
                    {{ formatEur(p.mark_price) }}
                  </td>
                  <td class="px-5 py-2 text-right" :class="pnlToneClass(tradePnlPct(p))">
                    {{ formatEur(tradePnl(p)) }}
                    <span class="text-xs">({{ formatPct(tradePnlPct(p), 1) }})</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </UCard>

          <!-- Trade log -->
          <UCard :ui="{ body: 'p-0' }">
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon name="i-lucide-activity" class="size-3.5 text-muted" />
                <h4 class="text-sm font-semibold">
                  Recent trades ({{ selectedLedger.trades?.length ?? 0 }})
                </h4>
                <span class="ml-auto text-xs text-muted">
                  {{ fg.historyExtent.value?.symbols
                    ? `${fg.historyExtent.value.symbols} symbols in history`
                    : 'history loading…' }}
                </span>
              </div>
            </template>
            <div v-if="!selectedLedger.trades?.length" class="px-5 py-6 text-sm text-muted">
              No trades yet. The strategy hasn't found an entry signal.
            </div>
            <ul v-else class="divide-y divide-default">
              <li v-for="(t, i) in selectedLedger.trades.slice(0, 25)" :key="i" class="px-5 py-3">
                <div class="mb-1 flex items-center gap-3">
                  <span
                    class="rounded px-2 py-0.5 font-mono text-xs uppercase"
                    :class="t.side === 'BUY'
                      ? 'bg-success/15 text-success'
                      : 'bg-error/15 text-error'"
                  >
                    {{ t.side }}
                  </span>
                  <span class="font-mono text-sm text-default">{{ t.symbol }}</span>
                  <span class="text-xs text-muted">
                    {{ t.qty?.toFixed?.(4) ?? t.qty }} @ {{ formatEur(t.price) }}
                  </span>
                  <span
                    v-if="t.pnl_eur !== undefined && t.pnl_eur !== null"
                    class="text-xs"
                    :class="pnlToneClass(t.pnl_eur)"
                  >
                    {{ t.pnl_eur >= 0 ? '+' : '' }}{{ formatEur(t.pnl_eur) }}
                  </span>
                  <span class="ml-auto text-xs text-muted">{{ relTime(t.ts) }}</span>
                </div>
                <div v-if="t.reason" class="flex items-start gap-1.5 pl-1 text-xs text-muted">
                  <UIcon name="i-lucide-info" class="mt-0.5 size-3 shrink-0 opacity-60" />
                  <span class="italic">{{ t.reason }}</span>
                </div>
              </li>
            </ul>
          </UCard>
        </div>
      </div>
    </div>
  </div>
</template>

