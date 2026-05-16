<!--
  CycleLogTable — zeigt die letzten Decide-Cycles (Scheduler + manuelle
  Trigger). Nutzt UTable mit Filterung nach Strategie + Status.
  Datenquelle: useFinanceGuru().cycles. VueUse refDebounced wird für die
  Strategiefilter-Eingabe verwendet (kein Spam-Re-Render).
-->
<script setup lang="ts">
import { refDebounced } from '@vueuse/core'
import { computed, h, ref, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { FinanceCycleRow, FinanceCycleSummary } from '~/types/api'
import { formatEur, formatPct, relTime } from '~/utils/format'

const props = defineProps<{
  cycles: FinanceCycleRow[]
  summary: FinanceCycleSummary | null
  strategies: string[]
}>()

const strategyFilter = ref<string>('all')
const statusFilter = ref<'all' | 'ok' | 'empty' | 'error'>('all')
const kindFilter = ref<'all' | 'builtin' | 'generated'>('all')
const search = ref('')
const debouncedSearch = refDebounced(search, 250)

const strategyItems = computed(() => [
  { label: 'Alle Strategien', value: 'all' },
  ...props.strategies.map(s => ({ label: s, value: s })),
])

const statusItems = [
  { label: 'Alle', value: 'all' },
  { label: 'OK', value: 'ok' },
  { label: 'Empty (kein Signal)', value: 'empty' },
  { label: 'Error', value: 'error' },
]

const kindItems = [
  { label: 'Alle Kinds', value: 'all' },
  { label: 'Builtin', value: 'builtin' },
  { label: 'Nur generierte', value: 'generated' },
]

const filteredCycles = computed(() => {
  const q = debouncedSearch.value.trim().toLowerCase()
  return props.cycles.filter((row) => {
    if (strategyFilter.value !== 'all' && row.strategy !== strategyFilter.value) return false
    if (statusFilter.value !== 'all' && row.status !== statusFilter.value) return false
    if (kindFilter.value !== 'all' && (row.kind || 'builtin') !== kindFilter.value) return false
    if (q) {
      const hay = `${row.strategy} ${row.trigger} ${row.error || ''}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
})

const UBadge = resolveComponent('UBadge')

const columns: TableColumn<FinanceCycleRow>[] = [
  {
    accessorKey: 'ts',
    header: 'Zeit',
    cell: ({ row }) => h(
      'div',
      { class: 'text-xs' },
      [
        h('div', { class: 'text-default' }, relTime(row.original.ts)),
        h('div', { class: 'text-muted' }, new Date(row.original.ts).toLocaleString()),
      ],
    ),
  },
  {
    accessorKey: 'strategy',
    header: 'Strategie',
    cell: ({ row }) => h('div', { class: 'flex flex-col gap-0.5' }, [
      h('span', { class: 'font-mono text-xs text-default' }, row.original.strategy),
      row.original.kind === 'generated'
        ? h(UBadge, { color: 'info', variant: 'subtle', size: 'xs' }, () => 'generated')
        : (row.original.kind === 'builtin'
          ? h(UBadge, { color: 'neutral', variant: 'subtle', size: 'xs' }, () => 'builtin')
          : null),
    ]),
  },
  {
    accessorKey: 'trigger',
    header: 'Trigger',
    cell: ({ row }) => h(UBadge, {
      color: row.original.trigger === 'scheduler' ? 'neutral' : 'primary',
      variant: 'subtle',
      size: 'xs',
    }, () => row.original.trigger),
  },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ row }) => {
      const map: Record<string, 'success' | 'warning' | 'error' | 'neutral'> = {
        ok: 'success', empty: 'neutral', error: 'error',
      }
      return h(UBadge, {
        color: map[row.original.status] || 'neutral',
        variant: 'subtle',
        size: 'xs',
      }, () => row.original.status)
    },
  },
  {
    accessorKey: 'signals',
    header: 'Signale',
    cell: ({ row }) => h('div', { class: 'text-xs tabular-nums' }, [
      h('span', { class: 'text-default' }, String(row.original.signals)),
      h('span', { class: 'ml-1 text-muted' }, `(${row.original.executed} exec / ${row.original.skipped} skip)`),
    ]),
  },
  {
    accessorKey: 'equity_eur',
    header: 'Equity',
    cell: ({ row }) => {
      const v = row.original.equity_eur
      return h('div', { class: 'text-right text-xs tabular-nums' }, [
        h('div', { class: 'text-default' }, v != null ? formatEur(v) : '–'),
        h(
          'div',
          {
            class: 'text-xs',
            style: { color: (row.original.pnl_pct ?? 0) >= 0 ? 'var(--ui-color-success-500)' : 'var(--ui-color-error-500)' },
          },
          row.original.pnl_pct != null ? formatPct(row.original.pnl_pct) : '',
        ),
      ])
    },
  },
  {
    accessorKey: 'duration_ms',
    header: 'Dauer',
    cell: ({ row }) => h('span', { class: 'text-xs text-muted tabular-nums' },
      row.original.duration_ms ? `${(row.original.duration_ms / 1000).toFixed(1)}s` : '–'),
  },
  {
    accessorKey: 'universe',
    header: 'Universe',
    cell: ({ row }) => h('span', { class: 'text-xs text-muted tabular-nums' }, String(row.original.universe || 0)),
  },
]

const expandRow = ref<FinanceCycleRow | null>(null)
</script>

<template>
  <UCard :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex flex-wrap items-center gap-3">
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-history" class="size-3.5 text-muted" />
          <h4 class="text-sm font-semibold">
            Cycle-Log
          </h4>
        </div>
        <div v-if="summary" class="flex items-center gap-2 text-xs text-muted">
          <UBadge color="neutral" variant="subtle" size="xs">
            {{ summary.total }} total
          </UBadge>
          <UBadge color="primary" variant="subtle" size="xs">
            {{ summary.last_24h }} in 24h
          </UBadge>
          <UBadge v-if="summary.errors > 0" color="error" variant="subtle" size="xs">
            {{ summary.errors }} errors
          </UBadge>
        </div>
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <UInput v-model="search" icon="i-lucide-search" placeholder="suchen…" size="xs" />
          <USelect v-model="strategyFilter" :items="strategyItems" size="xs" class="min-w-40" />
          <USelect v-model="kindFilter" :items="kindItems" size="xs" class="min-w-32" />
          <USelect v-model="statusFilter" :items="statusItems" size="xs" class="min-w-32" />
        </div>
      </div>
    </template>
    <div v-if="!cycles.length" class="px-5 py-8 text-center text-sm text-muted">
      Noch keine Cycles aufgezeichnet. Der Scheduler schreibt nach dem
      ersten Lauf ins Log.
    </div>
    <UTable
      v-else
      :data="filteredCycles"
      :columns="columns"
      sticky
      class="max-h-[480px]"
      :ui="{ td: 'py-1.5', th: 'py-2 text-xs' }"
      @select="(row) => (expandRow = row.original)"
    />
    <UModal
      :open="!!expandRow"
      :title="expandRow ? `${expandRow.strategy} – ${new Date(expandRow.ts).toLocaleString()}` : ''"
      :ui="{ content: 'max-w-2xl' }"
      @update:open="(o: boolean) => { if (!o) expandRow = null }"
    >
      <template #body>
        <div v-if="expandRow" class="space-y-3 text-sm">
          <div class="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
            <div>
              <div class="uppercase tracking-wider text-muted">
                Status
              </div>
              <div class="font-semibold">
                {{ expandRow.status }}
              </div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Signale
              </div>
              <div>{{ expandRow.signals }}</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Executed
              </div>
              <div>{{ expandRow.executed }}</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Skipped
              </div>
              <div>{{ expandRow.skipped }}</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Universe
              </div>
              <div>{{ expandRow.universe }}</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Dauer
              </div>
              <div>{{ (expandRow.duration_ms / 1000).toFixed(2) }}s</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Equity
              </div>
              <div>{{ expandRow.equity_eur != null ? formatEur(expandRow.equity_eur) : '–' }}</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Cash
              </div>
              <div>{{ expandRow.cash_eur != null ? formatEur(expandRow.cash_eur) : '–' }}</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Kind
              </div>
              <div>{{ expandRow.kind || '–' }}</div>
            </div>
            <div>
              <div class="uppercase tracking-wider text-muted">
                Backtest %
              </div>
              <div>{{ expandRow.bt_pnl_pct != null ? formatPct(expandRow.bt_pnl_pct) : '–' }}</div>
            </div>
          </div>
          <UAlert
            v-if="expandRow.error"
            color="error"
            variant="subtle"
            icon="i-lucide-alert-triangle"
            :title="expandRow.error"
          />
        </div>
      </template>
    </UModal>
  </UCard>
</template>

