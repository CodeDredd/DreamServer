<!--
  EquityChart — kompakter Equity-Verlauf einer Strategie über die letzten
  N Tage. Datenquelle: /api/finance-guru/equity-history (gefüllt aus dem
  Cycle-Log). Verwendet nuxt-charts (LineChart) analog zu LottoCharts.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { FinanceEquityPoint } from '~/types/api'
import { formatEur, formatPct } from '~/utils/format'

const props = defineProps<{
  points: FinanceEquityPoint[]
  seeded?: number
  height?: number
}>()

const height = computed(() => props.height ?? 220)

interface ChartRow { ts: string, equity: number, cash: number }

const chartData = computed<ChartRow[]>(() => {
  const points = props.points ?? []
  if (!points.length) return []
  return points.map(p => ({
    ts: p.ts,
    equity: Number(p.equity_eur ?? 0),
    cash: Number(p.cash_eur ?? 0),
  }))
})

const categories = computed(() => ({
  equity: { name: 'Equity', color: '#22c55e' },
  cash: { name: 'Cash', color: '#64748b' },
}))

const xFormatter = (i: number): string => {
  const row = chartData.value[i]
  if (!row) return ''
  const d = new Date(row.ts)
  return d.toLocaleDateString(undefined, { month: '2-digit', day: '2-digit' })
}

const yFormatter = (v: number) => `${Math.round(v)} €`

const minEquity = computed(() => Math.min(...chartData.value.map(d => d.equity), props.seeded ?? Infinity))
const maxEquity = computed(() => Math.max(...chartData.value.map(d => d.equity), props.seeded ?? -Infinity))

const last = computed<ChartRow | undefined>(() => chartData.value[chartData.value.length - 1])
const lastPnl = computed(() => {
  if (!last.value || !props.seeded) return null
  return ((last.value.equity - props.seeded) / props.seeded) * 100
})
</script>

<template>
  <UCard :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex items-center gap-2">
        <UIcon name="i-lucide-line-chart" class="size-3.5 text-muted" />
        <h4 class="text-sm font-semibold">
          Equity-Verlauf
        </h4>
        <span class="ml-auto text-xs text-muted">
          <template v-if="last">
            {{ formatEur(last.equity) }}
            <span v-if="lastPnl !== null" class="ml-1" :class="lastPnl >= 0 ? 'text-success' : 'text-error'">
              ({{ formatPct(lastPnl) }})
            </span>
          </template>
          <template v-else>
            keine Cycles
          </template>
        </span>
      </div>
    </template>
    <div v-if="!chartData.length" class="px-5 py-8 text-center text-sm text-muted">
      Noch keine Cycle-Daten — der Scheduler hat den Equity-Verlauf noch
      nicht aufgezeichnet. Triggere manuell „Decide now“ oder warte den
      nächsten Cron-Tick ab.
    </div>
    <div v-else class="p-3">
      <ClientOnly>
        <LineChart
          :data="chartData"
          :categories="categories"
          :y-axis="['equity', 'cash']"
          :height="height"
          :x-formatter="xFormatter"
          :y-formatter="yFormatter"
          :x-num-ticks="6"
          :y-num-ticks="4"
          curve-type="monotone"
        />
        <template #fallback>
          <div :style="{ height: `${height}px` }" class="flex items-center justify-center text-xs text-muted">
            Lade Chart…
          </div>
        </template>
      </ClientOnly>
      <div class="mt-2 flex items-center justify-between text-xs text-muted">
        <span>Range: {{ formatEur(minEquity) }} – {{ formatEur(maxEquity) }}</span>
        <span>{{ chartData.length }} Cycles</span>
      </div>
    </div>
  </UCard>
</template>



