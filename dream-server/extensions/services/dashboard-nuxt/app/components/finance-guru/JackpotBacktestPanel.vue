<!--
  Jackpot-Backtest — wendet jede Strategie ueber die letzten N Jahre
  auf die echten Ziehungen an und zeigt, wie oft jede Strategie
  welche Gewinnklasse getroffen haette. Stacked BarChart pro Strategie.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useLotto } from '~/composables/useLotto'
import type { LottoJackpotStrategy, LottoStrategyDescriptor } from '~/types/api'

const props = defineProps<{
  gameId: string | null
}>()

const lotto = useLotto()
const years = ref(10)
const rows = ref(1)

async function reload() {
  if (!props.gameId) return
  await lotto.fetchJackpotBacktest(props.gameId, {
    years: years.value, rows: rows.value,
  })
}
onMounted(reload)
watch(() => [props.gameId, years.value, rows.value], reload)

const tierKeys = computed<string[]>(() => {
  const per = lotto.jackpotBacktest.value?.per_strategy || {}
  const set = new Set<string>()
  for (const s of Object.values(per)) {
    for (const t of (s as LottoJackpotStrategy).tier_counts || []) set.add(t.key)
  }
  // Sort: class_1 first, class_2 second, … class_12 last.
  return Array.from(set).sort((a, b) => {
    const na = parseInt(a.replace(/\D/g, ''), 10) || 99
    const nb = parseInt(b.replace(/\D/g, ''), 10) || 99
    return na - nb
  })
})

const tierLabel = (key: string): string => {
  const per = lotto.jackpotBacktest.value?.per_strategy || {}
  for (const s of Object.values(per)) {
    const t = ((s as LottoJackpotStrategy).tier_counts || []).find(x => x.key === key)
    if (t) return t.label
  }
  return key
}

const strategyDescriptors = computed(() => {
  const m = new Map<string, LottoStrategyDescriptor>()
  for (const s of lotto.strategies.value) m.set(s.name, s)
  return m
})

// BarChart-Daten: pro Strategie eine Zeile, pro Tier eine Spalte.
const chartData = computed(() => {
  const per = lotto.jackpotBacktest.value?.per_strategy || {}
  return Object.entries(per).map(([name, s]) => {
    const row: Record<string, string | number> = { strategy: (strategyDescriptors.value.get(name)?.label || name) }
    const tcMap = new Map<string, number>(
      ((s as LottoJackpotStrategy).tier_counts || []).map(t => [t.key, t.count]),
    )
    for (const k of tierKeys.value) row[k] = tcMap.get(k) || 0
    return row
  })
})

// Farben fuer die Tiers — class_1 ist der "Hauptgewinn" (hervorgehoben).
const tierPalette = [
  '#facc15', // class_1 — gold
  '#f97316', // class_2 — amber
  '#fb7185', // class_3 — coral
  '#ec4899', // class_4 — pink
  '#a855f7', // class_5 — purple
  '#6366f1', // class_6 — indigo
  '#3b82f6', // class_7 — blue
  '#06b6d4', // class_8 — cyan
  '#10b981', // class_9 — emerald
  '#84cc16', // class_10 — lime
  '#a3a3a3', // class_11 — neutral
  '#737373', // class_12 — neutral
]

const categories = computed<Record<string, { name: string, color: string }>>(() => {
  const out: Record<string, { name: string, color: string }> = {}
  tierKeys.value.forEach((k, i) => {
    out[k] = { name: tierLabel(k), color: tierPalette[i] || '#9ca3af' }
  })
  return out
})

const yAxis = computed(() => tierKeys.value as unknown as string[])

const xFormatter = (i: number): string => {
  return String(chartData.value[i]?.strategy ?? '')
}

const totalsByStrategy = computed(() => {
  const per = lotto.jackpotBacktest.value?.per_strategy || {}
  return Object.entries(per).map(([name, s]) => {
    const sObj = s as LottoJackpotStrategy
    const total = (sObj.tier_counts || []).reduce((a, t) => a + (t.count || 0), 0)
    const jackpots = (sObj.tier_counts || []).find(t => t.key === 'class_1')?.count || 0
    const near = (sObj.tier_counts || []).find(t => t.key === 'class_2')?.count || 0
    return {
      name,
      label: strategyDescriptors.value.get(name)?.label || name,
      total,
      jackpots,
      near,
      n_trials: sObj.n_trials,
      best: sObj.best_match,
    }
  }).sort((a, b) => b.jackpots - a.jackpots || b.near - a.near || b.total - a.total)
})
</script>

<template>
  <UCard :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex items-center gap-2 flex-wrap">
        <UIcon name="i-lucide-trophy" class="size-4 text-warning" />
        <h4 class="text-sm font-semibold text-default">
          Hätte ich gewonnen? (Jackpot-Backtest über {{ years }} Jahre)
        </h4>
        <span class="text-[11px] text-muted">
          n_trials je Strategie: {{ lotto.jackpotBacktest.value?.per_strategy
            ? Object.values(lotto.jackpotBacktest.value.per_strategy)[0]?.n_trials ?? 0 : 0 }}
        </span>
        <div class="ml-auto flex items-center gap-2">
          <USelectMenu
            v-model="years"
            :items="[3, 5, 10, 15, 20].map(n => ({ label: `${n} Jahre`, value: n }))"
            value-key="value"
            size="xs"
          />
          <USelectMenu
            v-model="rows"
            :items="[1, 2, 3, 4].map(n => ({ label: `${n} Tipp/Strat`, value: n }))"
            value-key="value"
            size="xs"
          />
          <UButton
            icon="i-lucide-refresh-cw"
            size="xs"
            variant="ghost"
            color="neutral"
            :loading="lotto.jackpotLoading.value"
            @click="reload"
          />
        </div>
      </div>
    </template>

    <div v-if="lotto.jackpotError.value" class="p-5">
      <UAlert
        icon="i-lucide-alert-circle"
        color="error"
        variant="soft"
        :description="lotto.jackpotError.value"
      />
    </div>

    <div v-else-if="lotto.jackpotLoading.value && !lotto.jackpotBacktest.value" class="p-5 text-sm text-muted">
      Backtest läuft… (kann 1–3 s dauern)
    </div>

    <div v-else-if="!tierKeys.length" class="p-5 text-sm text-muted text-center">
      Noch keine Treffer in den letzten {{ years }} Jahren — das ist normal,
      die Wahrscheinlichkeit ist astronomisch klein.
      <span v-if="totalsByStrategy.length" class="block mt-2 text-[11px]">
        Beste je-Strategie Backtest-Trefferzahl: {{
          Math.max(...totalsByStrategy.map(t => (t.best as { main?: number, matches?: number })?.main ?? (t.best as { matches?: number })?.matches ?? 0))
        }} Übereinstimmungen.
      </span>
    </div>

    <div v-else class="p-5 space-y-4">
      <ClientOnly>
        <BarChart
          :data="chartData"
          :categories="categories"
          :y-axis="yAxis"
          :stacked="true"
          :height="320"
          :x-formatter="xFormatter"
          y-label="Anzahl Treffer"
          x-label="Strategie"
        />
        <template #fallback>
          <div class="h-[320px] flex items-center justify-center text-xs text-muted">Lade Chart…</div>
        </template>
      </ClientOnly>

      <!-- Strategy ranking table -->
      <div class="border-t border-default pt-3">
        <div class="grid grid-cols-12 text-[11px] text-muted mb-1 px-2">
          <div class="col-span-4">Strategie</div>
          <div class="col-span-2 text-right">Hauptgewinn</div>
          <div class="col-span-2 text-right">Nahezu</div>
          <div class="col-span-2 text-right">Treffer ges.</div>
          <div class="col-span-2 text-right">Bestes Ergebnis</div>
        </div>
        <div
          v-for="t in totalsByStrategy"
          :key="t.name"
          class="grid grid-cols-12 text-xs items-center py-1.5 px-2 border-t border-default/40"
        >
          <div class="col-span-4 truncate text-default">{{ t.label }}</div>
          <div class="col-span-2 text-right font-mono" :class="t.jackpots > 0 ? 'text-warning' : 'text-muted'">
            {{ t.jackpots }}
          </div>
          <div class="col-span-2 text-right font-mono" :class="t.near > 0 ? 'text-primary' : 'text-muted'">
            {{ t.near }}
          </div>
          <div class="col-span-2 text-right font-mono text-default">{{ t.total }}</div>
          <div class="col-span-2 text-right font-mono text-muted">
            <template v-if="t.best">
              <template v-if="(t.best as { main?: number }).main !== undefined">
                {{ (t.best as { main?: number }).main }}+{{ (t.best as { bonus?: number }).bonus }}
              </template>
              <template v-else>
                {{ (t.best as { matches?: number }).matches }} Endziffer
              </template>
            </template>
            <template v-else>—</template>
          </div>
        </div>
      </div>
    </div>
  </UCard>
</template>

