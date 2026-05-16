<!--
  Spielschein-Generator — Operator komponiert beliebige Felder
  (game, strategy, count) und bekommt sofort einen gerenderten
  Schein zurueck. Backend: POST /api/lotto/scheine/generate.

  Verwendet im Lotto-Tab (Finance-Guru) und als Widget auf der
  Dashboard-Startseite.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useLotto } from '~/composables/useLotto'
import { formatGermanDate } from '~/utils/format'
import type {
  LottoGame,
  LottoCustomScheinResponse,
  LottoScheinBlock,
} from '~/types/api'

interface FieldRow {
  game: string
  strategy: string | null
  count: number
}

const lotto = useLotto()

// Defaults: Sa/Mi-Schein-Look — 4× Lotto + 1× Spiel77 + 1× Super6.
const rows = ref<FieldRow[]>([
  { game: 'lotto-6aus49', strategy: null, count: 4 },
  { game: 'eurojackpot',  strategy: null, count: 4 },
  { game: 'spiel77',      strategy: null, count: 1 },
  { game: 'super6',       strategy: null, count: 1 },
])

const result = ref<LottoCustomScheinResponse | null>(null)
const generating = ref(false)
const error = ref<string | null>(null)

const gameOptions = computed(() =>
  (lotto.games.value || []).map(g => ({ label: g.label, value: g.id })),
)
function gameById(id: string): LottoGame | null {
  return (lotto.games.value || []).find(g => g.id === id) ?? null
}

// Strategies sind game-abhaengig — wir cachen je Game den Descriptor-Load
// einmalig. Initial reicht aber die statische Liste aus dem games-Endpoint
// nicht; wir holen on-demand.
const strategiesByGame = ref<Record<string, { name: string, label: string }[]>>({})
async function ensureStrategies(gameId: string) {
  if (strategiesByGame.value[gameId]) return
  try {
    const res = await $fetch<{ strategies: { name: string, label: string }[] }>(
      `/api/lotto/games/${encodeURIComponent(gameId)}/strategies?recency_k=${lotto.recencyK.value}`,
    )
    strategiesByGame.value[gameId] = res.strategies || []
  }
  catch { /* leave empty; auto wird gewaehlt */ }
}

function strategyOptions(gameId: string) {
  const items = strategiesByGame.value[gameId] || []
  return [{ label: 'Auto (Top-Strategie)', value: null as string | null },
          ...items.map(s => ({ label: s.label, value: s.name }))]
}

async function onGameChange(idx: number) {
  const row = rows.value[idx]
  if (!row) return
  row.strategy = null
  await ensureStrategies(row.game)
}
async function init() {
  if (!lotto.games.value?.length) await lotto.fetchOverview()
  for (const r of rows.value) await ensureStrategies(r.game)
}
void init()

function addRow() {
  rows.value.push({ game: 'lotto-6aus49', strategy: null, count: 1 })
  void ensureStrategies('lotto-6aus49')
}
function removeRow(idx: number) {
  rows.value.splice(idx, 1)
}

async function generate() {
  if (!rows.value.length) return
  generating.value = true
  error.value = null
  try {
    result.value = await lotto.generateCustomSchein(
      rows.value.map(r => ({
        game: r.game,
        strategy: r.strategy,
        count: r.count,
      })),
    )
  }
  catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  }
  finally {
    generating.value = false
  }
}

// Render-Helper fuer ein Feld (Lotto-Pool / Digit).
function fieldDisplay(block: LottoScheinBlock, idx: number): string {
  const f = block.fields[idx]
  if (!f) return ''
  if (f.display) return String(f.display)
  if (f.digits) return String(f.digits)
  return ''
}
function fieldPools(block: LottoScheinBlock, idx: number):
  Array<{ name: string, nums: number[], high: number, accent: boolean }> {
  const g = gameById(block.game_id)
  const f = block.fields[idx]
  if (!g || g.kind !== 'combinatorial' || !f) return []
  return (g.pools || []).map(p => ({
    name: p.name,
    high: p.high,
    accent: p.name !== 'Hauptzahlen',
    nums: ((f[p.name] as number[] | undefined) || []),
  }))
}

const blocks = computed(() => {
  const r = result.value?.schein
  if (!r) return []
  return Object.values(r).filter(b => (b.n_fields ?? 0) > 0)
})

const copied = ref<string | null>(null)
async function copyText(key: string, txt: string) {
  try {
    await navigator.clipboard.writeText(txt)
    copied.value = key
    setTimeout(() => (copied.value = null), 1200)
  }
  catch { /* */ }
}
</script>

<template>
  <UCard :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex items-center gap-2 flex-wrap">
        <UIcon name="i-lucide-clipboard-list" class="size-4 text-primary" />
        <h3 class="text-sm font-semibold text-default">
          Spielschein-Generator
        </h3>
        <span class="text-[11px] text-muted ml-2">
          beliebige Anzahl Felder × Strategie-Kombinationen
        </span>
        <UButton
          class="ml-auto"
          color="primary"
          size="sm"
          icon="i-lucide-sparkles"
          :loading="generating"
          :disabled="!rows.length"
          @click="generate"
        >
          Schein generieren
        </UButton>
      </div>
    </template>

    <!-- Feld-Definitionen -->
    <div class="px-5 py-4 space-y-2">
      <div
        v-for="(row, idx) in rows"
        :key="idx"
        class="grid grid-cols-12 gap-2 items-center"
      >
        <USelectMenu
          v-model="row.game"
          :items="gameOptions"
          value-key="value"
          class="col-span-4"
          @update:model-value="onGameChange(idx)"
        />
        <USelectMenu
          v-model="row.strategy"
          :items="strategyOptions(row.game)"
          value-key="value"
          class="col-span-5"
          placeholder="Auto (Top-Strategie)"
        />
        <UInputNumber
          v-model="row.count"
          :min="1"
          :max="12"
          class="col-span-2"
        />
        <UButton
          icon="i-lucide-trash-2"
          color="error"
          variant="ghost"
          size="xs"
          class="col-span-1 justify-self-end"
          :disabled="rows.length <= 1"
          @click="removeRow(idx)"
        />
      </div>
      <UButton
        icon="i-lucide-plus"
        size="xs"
        color="neutral"
        variant="outline"
        @click="addRow"
      >
        Feld hinzufügen
      </UButton>
    </div>

    <UAlert
      v-if="error"
      icon="i-lucide-alert-circle"
      color="error"
      variant="soft"
      class="mx-5 mb-4"
      :description="error"
    />

    <!-- Ergebnis -->
    <div v-if="blocks.length" class="border-t border-default px-5 py-4 space-y-4">
      <div
        v-for="block in blocks"
        :key="block.game_id"
        class="rounded-lg border border-default bg-elevated/30 p-3"
      >
        <div class="text-xs text-muted mb-2 flex items-center gap-2">
          <UIcon name="i-lucide-ticket" class="size-3 text-primary" />
          <span class="font-medium text-default">
            {{ gameById(block.game_id)?.label || block.game_id }}
          </span>
          <span>· {{ block.n_fields }} Feld{{ block.n_fields === 1 ? '' : 'er' }}</span>
        </div>
        <div class="space-y-2">
          <div
            v-for="(_f, fi) in block.fields"
            :key="fi"
            class="flex items-start gap-3 rounded-md bg-default border border-default/60 p-2"
          >
            <div class="text-[10px] font-mono text-muted w-6 shrink-0 mt-1">
              #{{ fi + 1 }}
            </div>
            <div class="flex-1 min-w-0">
              <div
                v-if="gameById(block.game_id)?.kind === 'digit'"
                class="flex items-center gap-1 font-mono text-xl tracking-widest text-default"
              >
                <span
                  v-for="(d, di) in (fieldDisplay(block, fi) || '').split('')"
                  :key="di"
                  class="inline-flex items-center justify-center w-7 h-9 rounded bg-elevated border border-default"
                >{{ d }}</span>
              </div>
              <div v-else class="space-y-1">
                <div
                  v-for="p in fieldPools(block, fi)"
                  :key="p.name"
                  class="flex items-center gap-1.5 flex-wrap"
                >
                  <span class="text-[10px] text-muted w-24 shrink-0">{{ p.name }}</span>
                  <span
                    v-for="(n, ni) in p.nums"
                    :key="ni"
                    :class="[
                      'inline-flex items-center justify-center w-7 h-7 rounded-full font-mono text-xs',
                      p.accent
                        ? 'bg-primary text-inverted'
                        : 'bg-elevated text-default border border-default',
                    ]"
                  >{{ p.high >= 10 ? String(n).padStart(2, '0') : n }}</span>
                </div>
              </div>
              <div
                v-if="block.fields[fi]?.strategy_label || block.fields[fi]?.rationale"
                class="text-[10px] text-muted italic mt-1"
              >
                <span v-if="block.fields[fi]?.strategy_label" class="text-default/80">
                  {{ block.fields[fi]?.strategy_label }}
                </span>
                <template v-if="block.fields[fi]?.rationale"> · {{ block.fields[fi]?.rationale }}</template>
              </div>
            </div>
            <button
              type="button"
              class="text-[11px] text-muted hover:text-default flex items-center gap-1 shrink-0"
              @click="copyText(`${block.game_id}-${fi}`, fieldDisplay(block, fi))"
            >
              <UIcon
                :name="copied === `${block.game_id}-${fi}` ? 'i-lucide-check' : 'i-lucide-copy'"
                class="size-3"
              />
              {{ copied === `${block.game_id}-${fi}` ? 'kopiert' : 'kopieren' }}
            </button>
          </div>
        </div>
      </div>
      <p class="text-[10px] text-muted">
        Hinweis: Es existiert keine offizielle Tipp-Abgabe-API. Die Tipps müssen
        manuell auf den Spielschein übertragen werden ({{ formatGermanDate(new Date().toISOString()) }}).
      </p>
    </div>
  </UCard>
</template>

