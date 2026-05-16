<!--
  Finance-Guru Strategies Tab (Phase F refactor).
  Aufbau:
    1. Aggregate KPI-Strip (5 Karten inkl. Cycles/24h).
    2. Equity-Chart der ausgewaehlten Strategie.
    3. Strategy-Liste (links) + Strategy-Detail (rechts).
       Positions + Trades sitzen in UCollapsible (Trades default zu).
  Cycle-Log + Enrichment-Workflow-Log leben jetzt in der "Cycles"-Tab
  (parent: trading.vue UTabs).
-->
<script setup lang="ts">
import { computed, h, ref, resolveComponent, watch } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import { useFinanceGuru } from '~/composables/useFinanceGuru'
import EquityChart from '~/components/finance-guru/EquityChart.vue'
import {
  formatEur,
  formatPct,
  pnlToneClass,
  relTime,
} from '~/utils/format'
import type {
  FinanceLedger,
  FinancePosition,
  FinanceStrategy,
  FinanceTrade,
} from '~/types/api'
const WEEKLY_TARGET_PCT = 10
const fg = useFinanceGuru()
const UBadge = resolveComponent('UBadge')
const decideLoading = ref(false)
const decideMsg = ref<{ tone: 'ok' | 'error', text: string } | null>(null)
const selectedName = ref<string | null>(null)
const positionsOpen = ref(true)
const tradesOpen = ref(false)
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
const selectedEquity = computed(() =>
  selectedName.value ? (fg.equity.value[selectedName.value] ?? []) : [],
)
async function runDecide(strategyName: string | null = null) {
  decideLoading.value = true
  decideMsg.value = null
  try {
    const res = await fg.decide(strategyName)
    decideMsg.value = { tone: 'ok', text: `Queued: ${res.queued_for || 'all-enabled'}` }
  }
  catch (e: unknown) {
    decideMsg.value = { tone: 'error', text: e instanceof Error ? e.message : String(e) }
  }
  finally {
    decideLoading.value = false
  }
}
function pnlOf(name: string): number | undefined {
  return fg.ledgers.value[name]?.kpi?.total_pnl_pct
}
function tradePnlPct(p: FinancePosition): number {
  return p.avg_price > 0 ? ((p.mark_price - p.avg_price) / p.avg_price) * 100 : 0
}
function tradePnl(p: FinancePosition): number {
  return (p.mark_price - p.avg_price) * p.qty
}
const positionColumns: TableColumn<FinancePosition>[] = [
  {
    accessorKey: 'symbol',
    header: 'Symbol',
    cell: ({ row }) => h('span', { class: 'font-mono text-sm text-default' }, row.original.symbol),
  },
  {
    accessorKey: 'qty',
    header: 'Qty',
    cell: ({ row }) => h('span', { class: 'tabular-nums' },
      row.original.qty?.toFixed?.(4) ?? String(row.original.qty)),
  },
  {
    accessorKey: 'avg_price',
    header: 'Avg',
    cell: ({ row }) => h('span', { class: 'tabular-nums' }, formatEur(row.original.avg_price)),
  },
  {
    accessorKey: 'mark_price',
    header: 'Mark',
    cell: ({ row }) => h('span', { class: 'tabular-nums' }, formatEur(row.original.mark_price)),
  },
  {
    id: 'pnl',
    header: 'PnL',
    cell: ({ row }) => {
      const pct = tradePnlPct(row.original)
      const eur = tradePnl(row.original)
      return h('div', { class: ['tabular-nums', pnlToneClass(pct)] }, [
        formatEur(eur),
        h('span', { class: 'ml-1 text-xs' }, `(${formatPct(pct, 1)})`),
      ])
    },
  },
]
const tradeColumns: TableColumn<FinanceTrade>[] = [
  {
    accessorKey: 'ts',
    header: 'Zeit',
    cell: ({ row }) => h('div', { class: 'text-xs text-muted' }, relTime(row.original.ts)),
  },
  {
    accessorKey: 'side',
    header: 'Side',
    cell: ({ row }) => h(UBadge, {
      color: row.original.side === 'BUY' ? 'success' : 'error',
      variant: 'subtle',
      size: 'xs',
    }, () => row.original.side),
  },
  {
    accessorKey: 'symbol',
    header: 'Symbol',
    cell: ({ row }) => h('span', { class: 'font-mono text-xs text-default' }, row.original.symbol),
  },
  {
    accessorKey: 'qty',
    header: 'Qty / Preis',
    cell: ({ row }) => h('div', { class: 'text-xs tabular-nums' },
      `${row.original.qty?.toFixed?.(4) ?? row.original.qty} @ ${formatEur(row.original.price)}`),
  },
  {
    accessorKey: 'pnl_eur',
    header: 'PnL',
    cell: ({ row }) => {
      const v = row.original.pnl_eur
      if (v == null) return h('span', { class: 'text-xs text-muted' }, '–')
      return h('span', {
        class: ['text-xs tabular-nums', pnlToneClass(v)],
      }, `${v >= 0 ? '+' : ''}${formatEur(v)}`)
    },
  },
  {
    accessorKey: 'reason',
    header: 'Reason',
    cell: ({ row }) => h('span', { class: 'text-xs text-muted line-clamp-2 max-w-md' }, row.original.reason || ''),
  },
]
</script>
<template>
  <div class="space-y-4">
    <UAlert v-if="fg.error.value" color="error" variant="subtle"
            icon="i-lucide-alert-circle"
            title="finance-guru-api not reachable"
    >
      <template #description>
        <p>{{ fg.error.value }}</p>
        <p class="mt-1 text-xs text-muted">
          Check <code class="font-mono">dream status finance-guru-api</code>.
        </p>
      </template>
    </UAlert>
    <UAlert v-if="decideMsg"
            :color="decideMsg.tone === 'ok' ? 'success' : 'error'"
            variant="subtle"
            :title="decideMsg.text"
            :close="{ onClick: () => (decideMsg = null) }"
    />
    <div v-if="fg.loading.value && !fg.strategies.value.length" class="space-y-3">
      <USkeleton class="h-20 rounded-xl" />
      <USkeleton class="h-64 rounded-xl" />
    </div>
    <!-- KPI strip — compacter than before -->
    <div v-if="fg.aggregate.value" class="grid grid-cols-2 gap-2 md:grid-cols-5">
      <UCard variant="subtle" :ui="{ body: 'p-3' }">
        <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-wallet" class="size-3" /> Seeded
        </div>
        <div class="mt-1 text-base font-semibold text-default tabular-nums">
          {{ formatEur(fg.aggregate.value.seeded) }}
        </div>
        <div class="text-[11px] text-muted">
          {{ fg.strategies.value.length }} Strategien
        </div>
      </UCard>
      <UCard variant="subtle" :ui="{ body: 'p-3' }">
        <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-coins" class="size-3" /> Equity
        </div>
        <div class="mt-1 text-base font-semibold tabular-nums"
             :class="fg.aggregate.value.totalPnlPct >= 0 ? 'text-success' : 'text-error'"
        >
          {{ formatEur(fg.aggregate.value.equity) }}
        </div>
        <div class="text-[11px] text-muted">
          {{ formatPct(fg.aggregate.value.totalPnlPct) }}
        </div>
      </UCard>
      <UCard variant="subtle" :ui="{ body: 'p-3' }">
        <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-target" class="size-3" /> vs Ziel
        </div>
        <div class="mt-1 text-base font-semibold tabular-nums"
             :class="fg.aggregate.value.totalPnlPct >= WEEKLY_TARGET_PCT ? 'text-success' : 'text-error'"
        >
          {{ formatPct(fg.aggregate.value.totalPnlPct - WEEKLY_TARGET_PCT) }}
        </div>
        <div class="text-[11px] text-muted">
          target {{ WEEKLY_TARGET_PCT }} %/Wo
        </div>
      </UCard>
      <UCard variant="subtle" :ui="{ body: 'p-3' }">
        <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-activity" class="size-3" /> Realised
        </div>
        <div class="mt-1 text-base font-semibold tabular-nums"
             :class="fg.aggregate.value.realised >= 0 ? 'text-success' : 'text-error'"
        >
          {{ formatEur(fg.aggregate.value.realised) }}
        </div>
        <div class="text-[11px] text-muted">
          {{ fg.aggregate.value.trades }} Trades
        </div>
      </UCard>
      <UCard variant="subtle" :ui="{ body: 'p-3' }">
        <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
          <UIcon name="i-lucide-history" class="size-3" /> Cycles 24h
        </div>
        <div class="mt-1 text-base font-semibold tabular-nums text-default">
          {{ fg.cycleSummary.value?.last_24h ?? 0 }}
        </div>
        <div class="text-[11px]"
             :class="(fg.cycleSummary.value?.errors ?? 0) > 0 ? 'text-error' : 'text-muted'"
        >
          {{ fg.cycleSummary.value?.errors ?? 0 }} Errors
        </div>
      </UCard>
    </div>
    <EquityChart v-if="selectedStrategy"
                 :points="selectedEquity"
                 :seeded="selectedLedger?.kpi?.seeded_eur"
    />
    <div class="grid gap-4 lg:grid-cols-3">
      <div class="space-y-2 lg:col-span-1">
        <h3 class="text-xs font-semibold uppercase tracking-wider text-muted">
          Strategien
        </h3>
        <button v-for="s in fg.strategies.value" :key="s.name" type="button"
                class="w-full rounded-lg border bg-elevated p-2.5 text-left transition-colors"
                :class="s.name === selectedName
                  ? 'border-primary'
                  : 'border-default hover:border-primary/50'"
                @click="selectedName = s.name"
        >
          <div class="mb-1.5 flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate font-mono text-xs text-default">
                {{ s.name }}
              </div>
              <div class="mt-0.5 text-[10px] text-muted">
                {{ s.asset_types?.join(' · ') || '' }}
              </div>
            </div>
            <span class="text-sm font-semibold tabular-nums"
                  :class="pnlToneClass(pnlOf(s.name))"
            >
              {{ formatPct(pnlOf(s.name)) }}
            </span>
          </div>
          <div class="flex items-center gap-2 text-[10px] text-muted">
            <span class="tabular-nums">{{ formatEur(fg.ledgers.value[s.name]?.kpi?.equity_eur) }}</span>
            <span>· {{ fg.ledgers.value[s.name]?.kpi?.n_positions ?? 0 }}p</span>
            <span>· {{ fg.ledgers.value[s.name]?.kpi?.n_trades ?? 0 }}t</span>
            <UBadge v-if="!s.enabled" color="warning" variant="subtle" size="xs" class="ml-auto">
              disabled
            </UBadge>
          </div>
        </button>
      </div>
      <div class="lg:col-span-2">
        <div v-if="!selectedStrategy || !selectedLedger"
             class="rounded-xl border border-default bg-elevated p-8 text-center text-muted"
        >
          {{ fg.strategies.value.length ? 'Select a strategy' : 'No strategies registered' }}
        </div>
        <div v-else class="space-y-3">
          <UCard variant="subtle">
            <template #header>
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0">
                  <h3 class="truncate font-mono text-sm font-semibold text-default">
                    {{ selectedStrategy.name }}
                  </h3>
                  <p class="mt-0.5 line-clamp-2 text-xs text-muted">
                    {{ selectedStrategy.description }}
                  </p>
                </div>
                <UButton color="neutral" variant="outline" size="xs"
                         :icon="decideLoading ? 'i-lucide-loader-2' : 'i-lucide-play'"
                         :loading="decideLoading" :disabled="decideLoading"
                         @click="runDecide(selectedStrategy.name)"
                >
                  Decide now
                </UButton>
              </div>
            </template>
            <div class="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div>
                <div class="text-[10px] uppercase tracking-wider text-muted">
                  Cash
                </div>
                <div class="mt-0.5 text-sm font-semibold tabular-nums">
                  {{ formatEur(selectedLedger.kpi?.cash_eur) }}
                </div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-muted">
                  Holdings
                </div>
                <div class="mt-0.5 text-sm font-semibold tabular-nums">
                  {{ formatEur(selectedLedger.kpi?.holdings_eur) }}
                </div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-muted">
                  Equity
                </div>
                <div class="mt-0.5 text-sm font-semibold tabular-nums">
                  {{ formatEur(selectedLedger.kpi?.equity_eur) }}
                </div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-muted">
                  PnL
                </div>
                <div class="mt-0.5 text-sm font-semibold tabular-nums"
                     :class="pnlToneClass(selectedLedger.kpi?.total_pnl_pct)"
                >
                  {{ formatPct(selectedLedger.kpi?.total_pnl_pct) }}
                </div>
              </div>
            </div>
            <template #footer>
              <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
                <span class="flex items-center gap-1">
                  <UIcon name="i-lucide-clock" class="size-3" />
                  last cycle {{ relTime(selectedStrategy.last_ts) }}
                </span>
                <span>signals: {{ selectedStrategy.last_signals ?? 0 }}</span>
                <span>executed: {{ selectedStrategy.last_executed ?? 0 }}</span>
                <span>skipped: {{ selectedStrategy.last_skipped ?? 0 }}</span>
                <span>
                  max pos: {{ ((selectedStrategy.max_position_frac || 0) * 100).toFixed(0) }}%
                </span>
              </div>
            </template>
          </UCard>
          <UCard variant="subtle" :ui="{ body: 'p-0' }">
            <UCollapsible v-model:open="positionsOpen" :ui="{ trigger: 'w-full' }">
              <template #default>
                <div class="flex items-center justify-between gap-2 px-4 py-2.5 hover:bg-elevated/40 cursor-pointer">
                  <div class="flex items-center gap-2">
                    <UIcon name="i-lucide-wallet" class="size-3.5 text-muted" />
                    <h4 class="text-sm font-semibold">
                      Open positions
                    </h4>
                    <UBadge variant="subtle" size="xs" color="neutral">
                      {{ selectedLedger.positions?.length ?? 0 }}
                    </UBadge>
                  </div>
                  <UIcon :name="positionsOpen ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
                         class="size-3.5 text-muted"
                  />
                </div>
              </template>
              <template #content>
                <div v-if="!selectedLedger.positions?.length"
                     class="border-t border-default px-5 py-5 text-sm text-muted"
                >
                  Strategy sitzt komplett in Cash.
                </div>
                <UTable v-else class="border-t border-default"
                        :data="selectedLedger.positions"
                        :columns="positionColumns"
                        :ui="{ td: 'py-1.5', th: 'py-2 text-xs' }"
                />
              </template>
            </UCollapsible>
          </UCard>
          <UCard variant="subtle" :ui="{ body: 'p-0' }">
            <UCollapsible v-model:open="tradesOpen" :ui="{ trigger: 'w-full' }">
              <template #default>
                <div class="flex items-center justify-between gap-2 px-4 py-2.5 hover:bg-elevated/40 cursor-pointer">
                  <div class="flex items-center gap-2">
                    <UIcon name="i-lucide-activity" class="size-3.5 text-muted" />
                    <h4 class="text-sm font-semibold">
                      Trades
                    </h4>
                    <UBadge variant="subtle" size="xs" color="neutral">
                      {{ selectedLedger.trades?.length ?? 0 }}
                    </UBadge>
                    <span class="ml-2 text-[11px] text-muted">
                      {{ fg.historyExtent.value?.symbols
                        ? `${fg.historyExtent.value.symbols} Symbole in History`
                        : 'History lädt…' }}
                    </span>
                  </div>
                  <UIcon :name="tradesOpen ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
                         class="size-3.5 text-muted"
                  />
                </div>
              </template>
              <template #content>
                <div v-if="!selectedLedger.trades?.length"
                     class="border-t border-default px-5 py-5 text-sm text-muted"
                >
                  Noch keine Trades.
                </div>
                <UTable v-else class="border-t border-default"
                        :data="selectedLedger.trades.slice(0, 50)"
                        :columns="tradeColumns"
                        sticky
                        :ui="{ td: 'py-1.5', th: 'py-2 text-xs',
                               root: 'max-h-[420px]' }"
                />
              </template>
            </UCollapsible>
          </UCard>
        </div>
      </div>
    </div>
  </div>
</template>
