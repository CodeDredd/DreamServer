<!--
  Lotto-Charts — visualisiert die /stats-Antwort mit nuxt-charts.
  Combinatorial (lotto/eurojackpot): BarChart Frequenz pro Zahl.
  Digit (spiel77/super6): pro Position BarChart Ziffer 0-9.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useLotto } from '~/composables/useLotto'
import type { LottoGame } from '~/types/api'

const lotto = useLotto()

const game = computed<LottoGame | null>(() => lotto.selectedGame.value)
const isDigit = computed(() => game.value?.kind === 'digit')
const mainPool = computed(() => game.value?.pools?.[0] ?? null)

interface FreqRow { number?: number, count: number, gap?: number }
const mainFrequency = computed<FreqRow[]>(() => {
  if (!mainPool.value || !lotto.stats.value) return []
  const bucket = lotto.stats.value[mainPool.value.name] as { frequency?: FreqRow[] } | undefined
  return bucket?.frequency || []
})

// Bar chart data for combinatorial: ein Datensatz pro Zahl.
const freqChartData = computed(() => mainFrequency.value.map(r => ({
  number: r.number ?? 0,
  count: r.count,
  gap: r.gap ?? 0,
})))

const freqCategories = computed(() => ({
  count: { name: 'Häufigkeit', color: '#38bdf8' },
}))

const freqXFormatter = (i: number): string => {
  const row = freqChartData.value[i]
  if (!row) return ''
  const high = mainPool.value?.high ?? 0
  return high >= 10 ? String(row.number).padStart(2, '0') : String(row.number)
}

// Gap chart data (separate line chart).
const gapChartData = computed(() => mainFrequency.value.map(r => ({
  number: r.number ?? 0,
  gap: r.gap ?? 0,
})))
const gapCategories = computed(() => ({
  gap: { name: 'Aktuelle Pause (Gap)', color: '#f97316' },
}))

// Digit game: per-position 0-9 counts.
const perPosition = computed(() => {
  return lotto.stats.value?.per_position || []
})
function digitChartData(positionIdx: number) {
  const pos = perPosition.value[positionIdx]
  if (!pos) return []
  return (pos.frequency || []).map(f => ({
    digit: String(f.digit),
    count: f.count,
  }))
}
const digitCategories = {
  count: { name: 'Häufigkeit', color: '#a855f7' },
}
function digitXFormatter(positionIdx: number) {
  return (i: number): string => {
    const data = digitChartData(positionIdx)
    return String(data[i]?.digit ?? '')
  }
}
</script>

<template>
  <UCard :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex items-center gap-2">
        <UIcon name="i-lucide-bar-chart-2" class="size-4 text-muted" />
        <h4 class="text-sm font-semibold text-default">
          Häufigkeits-Charts
        </h4>
        <span class="ml-auto text-[11px] text-muted">
          {{ lotto.stats.value?.n ?? 0 }} Ziehung(en)
        </span>
      </div>
    </template>

    <div v-if="!lotto.stats.value || lotto.stats.value.n === 0" class="p-5 text-sm text-muted">
      Noch keine Statistik verfügbar.
    </div>

    <!-- Combinatorial: ein Bar + ein Line -->
    <div v-else-if="!isDigit && freqChartData.length" class="p-5 space-y-5">
      <div>
        <p class="text-[11px] text-muted mb-2">
          {{ mainPool?.name }} – wie oft jede Zahl gezogen wurde.
        </p>
        <ClientOnly>
          <BarChart
            :data="freqChartData"
            :categories="freqCategories"
            :y-axis="['count']"
            :height="240"
            :x-formatter="freqXFormatter"
            :x-num-ticks="10"
            y-label="Anzahl"
            x-label="Zahl"
            :bar-padding="0.1"
          />
          <template #fallback>
            <div class="h-[240px] flex items-center justify-center text-xs text-muted">Lade…</div>
          </template>
        </ClientOnly>
      </div>
      <div>
        <p class="text-[11px] text-muted mb-2">
          Aktuelle Pause (Gap) je Zahl — wie viele Ziehungen sie nicht kam.
        </p>
        <ClientOnly>
          <LineChart
            :data="gapChartData"
            :categories="gapCategories"
            :y-axis="['gap']"
            :height="200"
            :x-formatter="freqXFormatter"
            :x-num-ticks="10"
            y-label="Gap"
            x-label="Zahl"
          />
          <template #fallback>
            <div class="h-[200px] flex items-center justify-center text-xs text-muted">Lade…</div>
          </template>
        </ClientOnly>
      </div>
    </div>

    <!-- Digit: pro Position ein kleines BarChart -->
    <div v-else-if="isDigit" class="p-5 space-y-4">
      <p class="text-[11px] text-muted">
        Häufigkeit der Ziffer 0–9 pro Position über die gesamte Historie.
        Eine echte Lotterie liefert ~{{ Math.round((lotto.stats.value?.n ?? 0) / 10) }}×
        je Ziffer (Erwartungswert).
      </p>
      <div class="grid sm:grid-cols-2 gap-4">
        <div v-for="pp in perPosition" :key="pp.position">
          <p class="text-[11px] text-muted mb-1">
            Position {{ pp.position + 1 }}
            <span v-if="game && pp.position === (game.digits - 1)" class="ml-1 text-warning">
              ← Endziffer (Spiel 77 Klasse 7)
            </span>
          </p>
          <ClientOnly>
            <BarChart
              :data="digitChartData(pp.position)"
              :categories="digitCategories"
              :y-axis="['count']"
              :height="150"
              :x-formatter="digitXFormatter(pp.position)"
              hide-legend
              :bar-padding="0.1"
            />
            <template #fallback>
              <div class="h-[150px] flex items-center justify-center text-xs text-muted">Lade…</div>
            </template>
          </ClientOnly>
        </div>
      </div>
    </div>
  </UCard>
</template>

