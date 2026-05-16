<!--
  Optimaler Schein — automatisch vor jeder Ziehung berechnet.
  Zeigt: 4× Lotto + 4× Eurojackpot + 1× Spiel77 + 1× Super6
  und die zwei kombinierten Sa/Mi- bzw. Di/Fr-Scheine.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useLotto } from '~/composables/useLotto'
import { formatGermanDate, relTime } from '~/utils/format'
import type { LottoGame, LottoScheinBlock } from '~/types/api'

const lotto = useLotto()

// Collapsible-State pro Rubrik. Default: nur die erste Rubrik offen,
// damit der Card-Block initial wenig Platz braucht. Persistiert ueber
// die Lebenszeit der Page; bei Neuberechnung des Scheins werden neue
// Rubriken automatisch geschlossen, bestehende behalten ihren State.
const openMap = ref<Record<string, boolean>>({})
const allOpen = computed({
  get: () => blocks.value.length > 0 && blocks.value.every(b => openMap.value[b.game_id]),
  set: (v: boolean) => {
    for (const b of blocks.value) openMap.value[b.game_id] = v
  },
})

onMounted(() => {
  if (!lotto.optimalSchein.value) void lotto.fetchOptimalSchein()
  if (!lotto.games.value?.length) void lotto.fetchOverview()
})

function gameById(id: string): LottoGame | null {
  return (lotto.games.value || []).find(g => g.id === id) ?? null
}

const orderedKeys = [
  'lotto-6aus49', 'eurojackpot', 'spiel77', 'super6',
  'combo_mittwoch_samstag', 'combo_dienstag_freitag',
]
const blocks = computed(() => {
  const s = lotto.optimalSchein.value?.schein
  if (!s) return [] as LottoScheinBlock[]
  return orderedKeys.map(k => s[k]).filter((b): b is LottoScheinBlock => !!b && (b.n_fields ?? 0) > 0)
})

// Bei der ersten Berechnung des Scheins (oder neu hinzugekommenen
// Rubriken) Default-State setzen: erste Rubrik offen, Rest zu.
watch(blocks, (list) => {
  let first = true
  for (const b of list) {
    if (!(b.game_id in openMap.value)) {
      openMap.value[b.game_id] = first
    }
    first = false
  }
}, { immediate: true })

function blockLabel(b: LottoScheinBlock): string {
  if (b.label) return b.label
  return gameById(b.game_id)?.label || b.game_id
}

function fieldPools(b: LottoScheinBlock, idx: number) {
  const f = b.fields[idx]
  const gid = (f as { game?: string })?.game || b.game_id
  const g = gameById(gid)
  if (!g || g.kind !== 'combinatorial' || !f) return null
  return (g.pools || []).map(p => ({
    name: p.name,
    high: p.high,
    accent: p.name !== 'Hauptzahlen',
    nums: ((f[p.name] as number[] | undefined) || []),
  }))
}

function nextDrawFor(gid: string): string | null {
  const map = lotto.optimalSchein.value?.next_draws || {}
  return map[gid] ?? null
}
</script>

<template>
  <UCard :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex items-center gap-2 flex-wrap">
        <UIcon name="i-lucide-target" class="size-4 text-primary" />
        <h3 class="text-sm font-semibold text-default">
          Optimaler Schein vor der nächsten Ziehung
        </h3>
        <span class="ml-auto text-[11px] text-muted">
          Top-N Strategien je Spiel (sortiert nach Backtest-Edge)
        </span>
        <UButton
          v-if="blocks.length"
          :icon="allOpen ? 'i-lucide-chevrons-down-up' : 'i-lucide-chevrons-up-down'"
          size="xs"
          variant="ghost"
          color="neutral"
          :title="allOpen ? 'Alle Rubriken einklappen' : 'Alle Rubriken ausklappen'"
          @click="allOpen = !allOpen"
        />
        <UButton
          icon="i-lucide-refresh-cw"
          size="xs"
          variant="ghost"
          color="neutral"
          :loading="lotto.optimalLoading.value"
          @click="lotto.fetchOptimalSchein()"
        />
      </div>
    </template>

    <div v-if="lotto.optimalError.value" class="px-5 py-3">
      <UAlert
        icon="i-lucide-alert-circle"
        color="error"
        variant="soft"
        :description="lotto.optimalError.value"
      />
    </div>

    <div v-else-if="!blocks.length && !lotto.optimalLoading.value" class="px-5 py-6 text-sm text-muted text-center">
      Noch kein Optimal-Schein berechnet.
    </div>

    <div v-else class="divide-y divide-default">
      <UCollapsible
        v-for="b in blocks"
        :key="b.game_id"
        v-model:open="openMap[b.game_id]"
      >
        <button
          type="button"
          class="w-full px-5 py-3 flex items-center gap-2 flex-wrap text-left hover:bg-elevated/30 transition-colors"
          :aria-expanded="!!openMap[b.game_id]"
        >
          <UIcon
            :name="openMap[b.game_id] ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
            class="size-3.5 text-muted shrink-0"
          />
          <span class="text-sm font-medium text-default">{{ blockLabel(b) }}</span>
          <span class="text-[10px] text-muted">· {{ b.n_fields }} Feld{{ b.n_fields === 1 ? '' : 'er' }}</span>
          <span
            v-if="nextDrawFor(b.game_id)"
            class="ml-auto text-[10px] text-primary font-mono"
          >
            Nächste Ziehung: {{ formatGermanDate(nextDrawFor(b.game_id)!) }}
            ({{ relTime(nextDrawFor(b.game_id)!) }})
          </span>
        </button>

        <template #content>
          <div class="px-5 pb-3">
            <div class="grid sm:grid-cols-2 gap-2">
              <div
                v-for="(f, fi) in b.fields"
                :key="fi"
                class="rounded-md bg-elevated/40 border border-default/60 p-2"
              >
                <div class="flex items-center gap-2 text-[10px] mb-1">
                  <span class="font-mono text-muted">#{{ fi + 1 }}</span>
                  <span class="text-default/80 truncate">
                    {{ (f as { strategy_label?: string }).strategy_label || f.strategy }}
                  </span>
                  <span
                    v-if="typeof (f as { strategy_edge?: number | null }).strategy_edge === 'number'"
                    :class="[
                      'ml-auto font-mono',
                      ((f as { strategy_edge?: number }).strategy_edge ?? 0) >= 0 ? 'text-success' : 'text-warning',
                    ]"
                  >
                    {{ ((f as { strategy_edge?: number }).strategy_edge ?? 0) >= 0 ? '+' : '' }}{{ (f as { strategy_edge?: number }).strategy_edge }}
                  </span>
                </div>
                <div v-if="fieldPools(b, fi)" class="space-y-0.5">
                  <div
                    v-for="p in fieldPools(b, fi)!"
                    :key="p.name"
                    class="flex items-center gap-1 flex-wrap"
                  >
                    <span class="text-[10px] text-muted w-20 shrink-0">{{ p.name }}</span>
                    <span
                      v-for="(n, ni) in p.nums"
                      :key="ni"
                      :class="[
                        'inline-flex items-center justify-center w-6 h-6 rounded-full font-mono text-[11px]',
                        p.accent
                          ? 'bg-primary text-inverted'
                          : 'bg-elevated text-default border border-default',
                      ]"
                    >{{ p.high >= 10 ? String(n).padStart(2, '0') : n }}</span>
                  </div>
                </div>
                <div
                  v-else-if="f.digits"
                  class="flex items-center gap-1 font-mono text-base tracking-widest text-default"
                >
                  <span
                    v-for="(d, di) in (f.digits || '').split('')"
                    :key="di"
                    class="inline-flex items-center justify-center w-6 h-8 rounded bg-elevated border border-default text-sm"
                  >{{ d }}</span>
                </div>
                <p
                  v-if="(f as { rationale?: string }).rationale"
                  class="mt-1 text-[10px] leading-snug text-muted"
                >
                  {{ (f as { rationale?: string }).rationale }}
                </p>
              </div>
            </div>
          </div>
        </template>
      </UCollapsible>
    </div>
  </UCard>
</template>

