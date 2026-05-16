<!--
  Lotto Oracle (Phase 4 Welle C.1b). Pendant zu
  dashboard/src/pages/LottoTab.jsx (~1011 LoC React) — der zweite Tab
  innerhalb der Finance-Guru-Page.

  Sub-Komponenten (NumberBall, ProbBar, TipDisplay) werden lokal via
  defineComponent + h() definiert; groessere Bloecke (RecencyOverlap,
  TipsCard, DrawsCard, StatsCard, SweetSpotPanel, RecencyKSelector,
  SubmissionNotice) bleiben inline im Template — analog zur
  extensions/index.vue-Konvention.
-->
<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { useLotto } from '~/composables/useLotto'
import { formatGermanDate, relTime } from '~/utils/format'
import OptimalScheinCard from '~/components/finance-guru/OptimalScheinCard.vue'
import SpielscheinGenerator from '~/components/finance-guru/SpielscheinGenerator.vue'
import LottoCharts from '~/components/finance-guru/LottoCharts.vue'
import JackpotBacktestPanel from '~/components/finance-guru/JackpotBacktestPanel.vue'
import type {
  LottoGame,
  LottoStrategyDescriptor,
  LottoStrategyMeta,
  LottoSweetSpotResponse,
  LottoTip,
} from '~/types/api'

const lotto = useLotto()

// Ersten Detail-Load nach Initial-Overview triggern (bei Tab-Switch
// auf Lotto: status/games kommen aus dem Modul-Cache, aber Detail
// ist component-local und initial leer).
onMounted(() => {
  if (lotto.selectedId.value && !lotto.tipsRun.value) {
    void lotto.fetchSelected(lotto.selectedId.value)
  }
})

// Auto-Regen-Drainer: wenn fetchSelected einen Mismatch zwischen
// persisted-K und sweet-spot-K erkennt, wird ein single-shot
// generate getriggert.
watch(
  () => [lotto.selectedId.value, lotto.tipsRun.value, lotto.busy.value],
  () => lotto.consumeAutoRegen(),
)

// Halte activeStrategy gueltig, wenn sich die Tip-Gruppen aendern.
const tipGroups = computed(() => {
  const tips = lotto.tipsRun.value?.tips || []
  const meta = lotto.tipsRun.value?.strategy_meta || {}
  const byStrat = new Map<string, (LottoTip & { _idx: number })[]>()
  tips.forEach((t, idx) => {
    if (!byStrat.has(t.strategy)) byStrat.set(t.strategy, [])
    byStrat.get(t.strategy)!.push({ ...t, _idx: idx })
  })
  const arr = Array.from(byStrat.entries()).map(([name, items]) => {
    const m: LottoStrategyMeta = meta[name] || {}
    const edge = typeof m.edge === 'number' ? m.edge : null
    return {
      name,
      items,
      meta: m,
      edge,
      sortKey: edge === null ? Number.NEGATIVE_INFINITY : edge,
    }
  })
  arr.sort((a, b) => b.sortKey - a.sortKey)
  return arr
})

const activeName = computed<string | null>(() => {
  if (!tipGroups.value.length) return null
  const cur = lotto.activeStrategy.value
  if (cur && tipGroups.value.some(g => g.name === cur)) return cur
  return tipGroups.value[0]?.name ?? null
})

watch(activeName, (name) => {
  if (name && name !== lotto.activeStrategy.value) {
    lotto.activeStrategy.value = name
  }
})

const activeGroup = computed(() =>
  tipGroups.value.find(g => g.name === activeName.value) ?? null,
)

const strategyMap = computed(() => {
  const m = new Map<string, LottoStrategyDescriptor>()
  for (const s of lotto.strategies.value) m.set(s.name, s)
  return m
})

// ---------- Copy-Zwischenablage ----------
const copied = ref<string | null>(null)
async function handleCopy(key: string, text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = key
    setTimeout(() => { copied.value = null }, 1500)
  }
  catch { /* ignore */ }
}

const recencyOptions = [1, 2, 3, 4, 5] as const

// ---------- Helpers fuer Strategy-Tone ----------
function strategyTone(m: LottoStrategyMeta): 'good' | 'warn' | 'neutral' {
  const hasScore = typeof m.edge === 'number' && (m.n_trials || 0) > 0
  if (!hasScore) return 'neutral'
  if ((m.edge ?? 0) > 0.05) return 'good'
  if ((m.edge ?? 0) < -0.05) return 'warn'
  return 'neutral'
}
function strategyToneCls(tone: 'good' | 'warn' | 'neutral'): string {
  if (tone === 'good') return 'text-success bg-success/10 border-success/30'
  if (tone === 'warn') return 'text-warning bg-warning/10 border-warning/30'
  return 'text-muted bg-elevated border-default'
}

// ---------- Inline-Helper-Components ----------

// NumberBall — fuer Hauptzahlen / Eurozahlen-Pools.
const NumberBall = defineComponent({
  name: 'LottoNumberBall',
  props: {
    value: { type: Number, required: true },
    pad: { type: Boolean, default: false },
    accent: { type: Boolean, default: false },
  },
  setup(props) {
    return () =>
      h(
        'span',
        {
          class: [
            'inline-flex items-center justify-center w-9 h-9 rounded-full text-sm font-mono font-semibold',
            props.accent
              ? 'bg-primary text-inverted'
              : 'bg-elevated text-default border border-default',
          ],
        },
        props.pad ? String(props.value).padStart(2, '0') : String(props.value),
      )
  },
})

// ProbBar — kleine Fortschrittsanzeige fuer p_at_least.
const ProbBar = defineComponent({
  name: 'LottoProbBar',
  props: {
    prob: { type: Number, default: 0 },
  },
  setup(props) {
    return () => {
      const pct = Math.round((props.prob || 0) * 100)
      return h('div', { class: 'flex items-center gap-2 w-32' }, [
        h(
          'div',
          { class: 'flex-1 h-2 bg-default/60 rounded-sm overflow-hidden' },
          h('div', {
            class: 'h-full bg-primary/70',
            style: { width: `${pct}%` },
          }),
        ),
        h(
          'span',
          { class: 'font-mono text-muted w-9 text-right' },
          `${pct}%`,
        ),
      ])
    }
  },
})

// TipDisplay — rendert digit-Strings (Spiel77/Super6) oder Zahlen-
// Pools (Lotto 6aus49 / Eurojackpot).
const TipDisplay = defineComponent({
  name: 'LottoTipDisplay',
  props: {
    game: { type: Object as () => LottoGame, required: true },
    tip: { type: Object as () => Record<string, unknown>, required: true },
  },
  setup(props) {
    return () => {
      if (props.game.kind === 'digit') {
        const digits = (props.tip.digits as string) || ''
        return h(
          'div',
          { class: 'flex items-center gap-1 font-mono text-2xl tracking-widest text-default' },
          digits.split('').map((d, i) =>
            h(
              'span',
              {
                key: i,
                class: 'inline-flex items-center justify-center w-9 h-11 rounded bg-elevated border border-default',
              },
              d,
            ),
          ),
        )
      }
      const pools = props.game.pools || []
      return h(
        'div',
        { class: 'space-y-2' },
        pools.map(p =>
          h('div', { key: p.name, class: 'flex items-center gap-2 flex-wrap' }, [
            h('span', { class: 'text-xs text-muted w-28 shrink-0' }, p.name),
            ...((props.tip[p.name] as number[] | undefined) || []).map((n, i) =>
              h(NumberBall, {
                key: i,
                value: n,
                pad: p.high >= 10,
                accent: p.name !== 'Hauptzahlen',
              }),
            ),
          ]),
        ),
      )
    }
  },
})

// usedK fuer die Tipps-Header-Zeile.
const usedK = computed<number | undefined>(
  () => lotto.tipsRun.value?.params?.recency_k,
)

// Recency-Overlap — wir rendern, wenn lookbacks samples haben.
const recencyLookbacks = computed(() => {
  const stats = lotto.tipsRun.value?.recency_stats
  if (!stats?.lookbacks) return []
  return ['1', '2', '3'].filter((k) => {
    const b = stats.lookbacks?.[k]
    return b && (b.samples || 0) > 0
  })
})
const recencyKind = computed(() => lotto.tipsRun.value?.recency_stats?.kind)

// Sweet-Spot Helper — sweetSpotRow-Klassen.
function sweetSpotCellCls(rowK: number, sweet: LottoSweetSpotResponse | null): string {
  if (!sweet) return 'border-default bg-default text-muted'
  if (rowK === lotto.recencyK.value) {
    return 'border-primary bg-primary/10 text-default'
  }
  if (rowK === sweet.recommended_k) {
    return 'border-success/40 bg-success/5 text-default'
  }
  return 'border-default bg-default text-muted'
}

function refreshAll(): void {
  void lotto.fetchOverview()
  if (lotto.selectedId.value) void lotto.fetchSelected(lotto.selectedId.value)
}

function statsMaxCount(rows: { count: number }[] | undefined): number {
  if (!rows?.length) return 1
  return Math.max(1, ...rows.map(r => r.count))
}

function statsMainPool(game: LottoGame | null) {
  return game?.pools?.[0] ?? null
}

function statsMainData(game: LottoGame | null): { number?: number, count: number, gap?: number }[] {
  const main = statsMainPool(game)
  if (!main || !lotto.stats.value) return []
  const bucket = lotto.stats.value[main.name] as { frequency?: { number?: number, count: number, gap?: number }[] } | undefined
  return bucket?.frequency || []
}
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-6 flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h2 class="text-xl font-semibold text-default flex items-center gap-2">
          <UIcon name="i-lucide-ticket" class="size-5 text-primary" />
          Lotto Oracle
        </h2>
        <p class="text-muted mt-1 max-w-2xl text-sm">
          Sammelt Ziehungen (Lotto 6 aus 49, Eurojackpot, Spiel 77, Super 6)
          und generiert nach jeder Ziehung neue Tipps via mehrerer Strategien.
        </p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <!-- RecencyKSelector inline -->
        <div
          class="flex items-center gap-2 text-xs text-muted px-2 py-1.5 rounded-lg border border-default bg-default"
          title="Wie viele der jüngsten Ziehungen soll die recency_exclude-Strategie ausschließen?"
        >
          <span class="font-medium">Recency K</span>
          <div class="flex items-center gap-0.5" role="group" aria-label="Recency K wählen">
            <button
              v-for="k in recencyOptions"
              :key="k"
              type="button"
              :disabled="!!lotto.busy.value || !lotto.status.value?.available"
              :class="[
                'w-7 h-7 rounded-md font-mono text-sm flex items-center justify-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
                k === lotto.recencyK.value
                  ? 'border border-primary bg-primary text-inverted font-semibold'
                  : k === lotto.sweetSpot.value?.recommended_k
                    ? 'border border-success/50 bg-success/10 text-success hover:bg-success/20'
                    : 'border border-transparent text-muted hover:bg-elevated hover:text-default',
              ]"
              :title="
                k === lotto.sweetSpot.value?.recommended_k
                  ? `K=${k} — empirisch empfohlener Wert (Sweet-Spot)`
                  : `K=${k} — recency_exclude wird die letzten ${k} Ziehung(en) ausschließen`
              "
              @click="lotto.handleKChange(k)"
            >
              {{ k }}
            </button>
          </div>
          <UIcon
            v-if="lotto.busy.value === 'generate'"
            name="i-lucide-loader-circle"
            class="size-3 animate-spin text-primary"
          />
          <span
            v-else-if="
              lotto.sweetSpot.value?.recommended_k
                && lotto.sweetSpot.value.recommended_k !== lotto.recencyK.value
            "
            class="text-[10px] text-success ml-1"
          >
            Empfohlen: {{ lotto.sweetSpot.value.recommended_k }}
          </span>
        </div>
        <UButton
          icon="i-lucide-refresh-cw"
          variant="ghost"
          color="neutral"
          size="sm"
          title="Refresh"
          @click="refreshAll"
        />
        <UButton
          variant="outline"
          color="neutral"
          size="sm"
          :loading="lotto.busy.value === 'refresh'"
          icon="i-lucide-database"
          :disabled="!!lotto.busy.value || !lotto.status.value?.available"
          title="Inkrementell neue Ziehungen abholen"
          @click="lotto.doAction('refresh')"
        >
          Fetch
        </UButton>
        <UButton
          variant="outline"
          color="neutral"
          size="sm"
          :loading="lotto.busy.value === 'backfill'"
          icon="i-lucide-database"
          :disabled="!!lotto.busy.value || !lotto.status.value?.available"
          title="Komplette Historie nachladen (kann Minuten dauern)"
          @click="lotto.doAction('backfill')"
        >
          Backfill
        </UButton>
        <UButton
          color="primary"
          size="sm"
          :loading="lotto.busy.value === 'generate'"
          icon="i-lucide-sparkles"
          :disabled="!!lotto.busy.value || !lotto.status.value?.available || !lotto.selectedId.value"
          title="Neue Tipps für die ausgewählte Spielart generieren"
          @click="lotto.doAction('generate')"
        >
          Tipps generieren
        </UButton>
      </div>
    </div>

    <!-- Submission-API hinweis -->
    <UAlert
      v-if="lotto.status.value?.submission_api?.note"
      icon="i-lucide-info"
      color="warning"
      variant="soft"
      class="mb-6"
    >
      <template #description>
        <span class="font-medium">Keine reale Tippabgabe via API möglich.</span>
        {{ ' ' }}{{ lotto.status.value.submission_api.note }}
      </template>
    </UAlert>

    <!-- Error -->
    <UAlert
      v-if="lotto.overviewError.value || lotto.detailError.value"
      icon="i-lucide-alert-circle"
      color="error"
      variant="soft"
      class="mb-6"
      title="lotto-oracle nicht erreichbar"
    >
      <template #description>
        <div>{{ lotto.overviewError.value || lotto.detailError.value }}</div>
        <div class="opacity-60 mt-1 text-xs">
          Prüfe <code class="font-mono">dream status lotto-oracle</code> auf dem Host.
        </div>
      </template>
    </UAlert>

    <!-- Busy-Toast (inline) -->
    <UAlert
      v-if="lotto.busyMsg.value"
      :color="lotto.busyMsg.value.tone === 'ok' ? 'success' : 'error'"
      variant="soft"
      class="mb-6"
      :description="lotto.busyMsg.value.text"
    />

    <!-- Optimal-Schein + Spielschein-Generator (immer sichtbar, game-uebergreifend) -->
    <div class="mb-6 grid lg:grid-cols-2 gap-4">
      <OptimalScheinCard />
      <SpielscheinGenerator />
    </div>

    <!-- Game selector cards -->
    <div class="mb-6 grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
      <button
        v-for="g in lotto.games.value"
        :key="g.id"
        type="button"
        :class="[
          'p-4 rounded-xl text-left border transition-colors',
          g.id === lotto.selectedId.value
            ? 'bg-default border-primary'
            : 'bg-default border-default hover:border-primary/50',
        ]"
        @click="lotto.selectGame(g.id)"
      >
        <div class="flex items-center justify-between mb-1">
          <span class="font-medium text-default">{{ g.label }}</span>
          <span class="text-xs text-muted">{{ g.n_draws ?? 0 }} Ziehungen</span>
        </div>
        <div class="text-xs text-muted">
          <template v-if="g.kind === 'digit'">
            {{ g.digits }}-stellige Losnummer
          </template>
          <template v-else>
            {{ (g.pools || []).map(p => `${p.pick}/${p.high}`).join(' + ') }}
          </template>
        </div>
        <div class="text-xs text-muted mt-1 flex items-center gap-1">
          <UIcon name="i-lucide-calendar" class="size-3" />
          {{ (g.draw_days || []).join(' · ').toUpperCase() }}
        </div>
        <div class="text-xs text-muted mt-1">
          Letzte: <span class="font-mono">{{ formatGermanDate(g.last_in_db) }}</span>
        </div>
      </button>
    </div>

    <!-- Schedule strip -->
    <div
      v-if="lotto.status.value?.schedule"
      class="mb-6 p-3 bg-default border border-default rounded-lg flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted"
    >
      <span class="flex items-center gap-1">
        <UIcon name="i-lucide-clock" class="size-3" />
        Auto-Update Cron
        <code class="font-mono">{{ lotto.status.value.schedule.cron }}</code>
        ({{ lotto.status.value.schedule.tz }})
      </span>
      <span>• Tipps werden nach jedem Fetch automatisch neu generiert</span>
      <span>• Quelle: lotto-oracle</span>
    </div>

    <!-- Two-column detail -->
    <div v-if="lotto.selectedGame.value" class="grid lg:grid-cols-3 gap-6">
      <!-- Left: tips + recency overlap + draws -->
      <div class="lg:col-span-2 space-y-6">
        <!-- RecencyOverlapCard -->
        <UCard
          v-if="recencyLookbacks.length"
          :ui="{ body: 'p-0' }"
        >
          <template #header>
            <div class="flex items-center gap-2">
              <UIcon name="i-lucide-bar-chart-3" class="size-4 text-muted" />
              <h4 class="text-sm font-semibold text-default">
                Wiederholungs-Wahrscheinlichkeiten
              </h4>
              <span class="ml-auto text-[11px] text-muted">
                empirisch über {{ lotto.tipsRun.value?.recency_stats?.n_history }} Ziehung(en) ·
                Vergleich:
                {{
                  recencyKind === 'combinatorial'
                    ? `Zahlen aus ${lotto.tipsRun.value?.recency_stats?.main_pool || 'Hauptpool'}`
                    : 'Positionen mit gleicher Ziffer'
                }}
              </span>
            </div>
          </template>
          <div class="p-5 grid sm:grid-cols-3 gap-4">
            <div
              v-for="N in recencyLookbacks"
              :key="N"
              class="border border-default rounded-lg p-3 bg-elevated/40"
            >
              <div class="text-xs text-muted mb-1">
                Letzte {{ N }} Ziehung{{ N === '1' ? '' : 'en' }}
              </div>
              <div class="text-2xl font-mono text-default">
                {{
                  lotto.tipsRun.value?.recency_stats?.lookbacks?.[N]?.mean != null
                    ? lotto.tipsRun.value!.recency_stats!.lookbacks![N].mean!.toFixed(2)
                    : '—'
                }}
              </div>
              <div class="text-[11px] text-muted mb-2">
                ⌀ wieder gezogen (random ≈
                {{ lotto.tipsRun.value?.recency_stats?.lookbacks?.[N]?.expected_random }})
              </div>
              <ul class="space-y-1">
                <li
                  v-for="row in (lotto.tipsRun.value?.recency_stats?.lookbacks?.[N]?.p_at_least || []).slice(0, 4)"
                  :key="row.k"
                  class="flex items-center justify-between gap-2 text-[11px]"
                >
                  <span class="text-muted">P(≥ {{ row.k }} Treffer)</span>
                  <ProbBar :prob="row.prob" />
                </li>
              </ul>
            </div>
          </div>
          <template #footer>
            <div class="text-[11px] text-muted">
              <template v-if="recencyKind === 'combinatorial'">
                Lies dies als: „Wie oft kamen aus den letzten <em>N</em> Ziehungen
                noch <em>k</em> Hauptzahlen wieder?". Werte ≈ Random-Erwartung
                sind das Lehrbuch (Ziehungen sind unabhängig).
              </template>
              <template v-else>
                Lies dies als: „Wie oft hatte die nächste Ziehung an gleicher
                Position dieselbe Ziffer wie eine der letzten <em>N</em>?".
                P(≥1) liegt für N=3 nahe 100 % — die ‚letzte-Ziehung-ausschließen'-Strategie
                verschenkt also bewusst diese Treffer.
              </template>
            </div>
          </template>
        </UCard>

        <!-- TipsCard -->
        <UCard :ui="{ body: 'p-0' }">
          <template #header>
            <div class="flex items-center gap-2 flex-wrap">
              <UIcon name="i-lucide-sparkles" class="size-4 text-muted" />
              <h4 class="text-sm font-semibold text-default">
                Vorschläge ({{ lotto.tipsRun.value?.tips?.length ?? 0 }})
              </h4>
              <span class="ml-auto text-xs text-muted">
                <template v-if="lotto.tipsRun.value">
                  generiert {{ relTime(lotto.tipsRun.value.generated_at) }}
                  · basierend auf {{ lotto.tipsRun.value.based_on_draw || '—' }}
                  <template v-if="typeof usedK === 'number'">
                    · K={{ usedK }}
                  </template>
                  · sortiert nach Backtest-Edge
                </template>
                <template v-else>
                  Noch keine Tipps generiert — auf "Tipps generieren" klicken.
                </template>
              </span>
            </div>
          </template>

          <template v-if="tipGroups.length">
            <!-- Tab-Strip -->
            <div class="flex flex-wrap gap-1 px-3 pt-3 pb-0 border-b border-default bg-elevated/20">
              <button
                v-for="g in tipGroups"
                :key="g.name"
                type="button"
                :class="[
                  'px-3 py-1.5 text-xs font-medium rounded-t-md border-b-2 transition-colors flex items-center gap-2',
                  g.name === activeName
                    ? 'border-primary text-default bg-default'
                    : 'border-transparent text-muted hover:text-default hover:bg-default/50',
                ]"
                :title="strategyMap.get(g.name)?.description || g.name"
                @click="lotto.activeStrategy.value = g.name"
              >
                <span>{{ strategyMap.get(g.name)?.label || g.name }}</span>
                <span class="text-[10px] opacity-70">({{ g.items.length }})</span>
                <span
                  v-if="typeof g.meta.edge === 'number' && (g.meta.n_trials || 0) > 0"
                  :class="[
                    'text-[10px] font-mono',
                    g.name === activeName
                      ? ''
                      : strategyTone(g.meta) === 'good'
                        ? 'text-success/70'
                        : strategyTone(g.meta) === 'warn'
                          ? 'text-warning/70'
                          : 'text-muted',
                  ]"
                >
                  {{ (g.meta.edge ?? 0) >= 0 ? '+' : '' }}{{ g.meta.edge }}
                </span>
              </button>
            </div>

            <!-- Active-Tab-Body -->
            <div v-if="activeGroup" class="px-5 py-4">
              <div class="flex items-start justify-between gap-3 mb-3">
                <div class="min-w-0">
                  <div
                    v-if="strategyMap.get(activeGroup.name)?.description"
                    class="text-xs text-muted max-w-xl"
                  >
                    {{ strategyMap.get(activeGroup.name)?.description }}
                  </div>
                </div>
                <div
                  v-if="typeof activeGroup.meta.edge === 'number' && (activeGroup.meta.n_trials || 0) > 0"
                  :class="[
                    'shrink-0 text-[10px] font-mono px-2 py-1 rounded border flex items-center gap-1',
                    strategyToneCls(strategyTone(activeGroup.meta)),
                  ]"
                  :title="
                    `Backtest über ${activeGroup.meta.n_trials} Tipps gegen ${activeGroup.meta.window} echte Ziehungen.\n`
                      + `⌀ Treffer: ${activeGroup.meta.avg_match} (random: ${activeGroup.meta.expected_random})\n`
                      + `Edge = avg − random = ${(activeGroup.meta.edge ?? 0) >= 0 ? '+' : ''}${activeGroup.meta.edge}`
                  "
                >
                  <UIcon name="i-lucide-trending-up" class="size-3" />
                  <span>⌀ {{ activeGroup.meta.avg_match }} {{ (activeGroup.meta.edge ?? 0) >= 0 ? '+' : '' }}{{ activeGroup.meta.edge }}</span>
                </div>
                <div
                  v-else
                  class="shrink-0 text-[10px] text-muted px-2 py-1 rounded border border-default"
                >
                  Backtest n/a
                </div>
              </div>

              <!-- SweetSpotPanel — nur fuer recency_exclude -->
              <div
                v-if="
                  activeGroup.name === 'recency_exclude'
                    && (lotto.sweetSpot.value?.per_k?.length ?? 0) > 0
                "
                class="mb-4 p-3 rounded-lg border border-default bg-elevated/30"
              >
                <div class="flex items-center gap-2 mb-2 text-xs text-muted">
                  <UIcon name="i-lucide-bar-chart-3" class="size-3" />
                  <span>
                    Recency-Backtest pro K (Ø Treffer im Hauptpool über
                    {{ lotto.sweetSpot.value?.window || 0 }} historische Ziehungen)
                  </span>
                  <span
                    v-if="lotto.sweetSpot.value?.recommended_k"
                    class="ml-auto text-success"
                  >
                    Empfehlung: K={{ lotto.sweetSpot.value.recommended_k }}
                  </span>
                </div>
                <div class="grid grid-cols-5 gap-1.5">
                  <div
                    v-for="row in lotto.sweetSpot.value!.per_k"
                    :key="row.k"
                    :class="[
                      'text-center text-[11px] py-1.5 rounded border',
                      sweetSpotCellCls(row.k, lotto.sweetSpot.value),
                    ]"
                    :title="
                      `K=${row.k}: ⌀ Treffer ${row.avg_match ?? '—'} `
                        + `(random ${row.expected_random ?? '—'}, `
                        + `Edge ${row.edge ?? '—'}, n=${row.n_trials ?? 0})`
                    "
                  >
                    <div class="font-mono">
                      K={{ row.k }}
                    </div>
                    <div class="font-mono opacity-80">
                      {{ row.avg_match != null ? row.avg_match.toFixed(2) : '—' }}
                    </div>
                  </div>
                </div>
                <div class="mt-2 text-[10px] text-muted leading-snug">
                  Lotto ist statistisch unabhängig — Unterschiede zwischen den
                  K-Werten sind klein (≪ ±0.1 Treffer). Empfohlen wird das K mit
                  dem höchsten empirischen Ø-Treffer; bei Gleichstand das
                  kleinere K, weil jedes zusätzlich ausgeschlossene Spiel den
                  Pool unnötig verkleinert.
                </div>
              </div>

              <div class="space-y-3">
                <div
                  v-for="t in activeGroup.items"
                  :key="t._idx"
                  class="rounded-lg bg-elevated/40 border border-default/60 p-3"
                >
                  <div class="flex items-start justify-between gap-3 mb-2">
                    <div
                      v-if="t.rationale"
                      class="text-[11px] text-muted italic max-w-xl"
                    >
                      {{ t.rationale }}
                    </div>
                    <button
                      type="button"
                      class="shrink-0 text-xs text-muted hover:text-default flex items-center gap-1"
                      title="Tipp in die Zwischenablage kopieren"
                      @click="handleCopy(`tip-${t._idx}`, t.display || '')"
                    >
                      <template v-if="copied === `tip-${t._idx}`">
                        <UIcon name="i-lucide-check" class="size-3" /> kopiert
                      </template>
                      <template v-else>
                        <UIcon name="i-lucide-copy" class="size-3" /> kopieren
                      </template>
                    </button>
                  </div>
                  <TipDisplay :game="lotto.selectedGame.value!" :tip="t" />
                </div>
              </div>
            </div>
          </template>
          <div v-else class="px-5 py-8 text-sm text-muted text-center">
            Noch keine Vorschläge. Klicke oben auf <strong>Tipps generieren</strong>.
          </div>
        </UCard>

        <!-- DrawsCard -->
        <UCard :ui="{ body: 'p-0' }">
          <template #header>
            <div class="flex items-center gap-2">
              <UIcon name="i-lucide-calendar" class="size-4 text-muted" />
              <h4 class="text-sm font-semibold text-default">
                Letzte Ziehungen ({{ lotto.draws.value.length }})
              </h4>
            </div>
          </template>
          <ul
            v-if="lotto.draws.value.length"
            class="divide-y divide-default"
          >
            <li
              v-for="(d, i) in lotto.draws.value"
              :key="i"
              class="px-5 py-3 flex items-start gap-4"
            >
              <div class="text-xs font-mono text-muted w-24 shrink-0 mt-1">
                {{ formatGermanDate(d.draw_date) }}
              </div>
              <div class="flex-1">
                <TipDisplay :game="lotto.selectedGame.value!" :tip="d" />
              </div>
            </li>
          </ul>
          <div v-else class="px-5 py-6 text-sm text-muted">
            Keine Ziehungen geladen — bitte zuerst <strong>Backfill</strong> klicken.
          </div>
        </UCard>
      </div>

      <!-- Right: stats -->
      <div class="lg:col-span-1">
        <!-- StatsCard -->
        <UCard
          v-if="!lotto.stats.value || lotto.stats.value.n === 0"
          :ui="{ body: 'p-5' }"
        >
          <p class="text-sm text-muted">
            Keine Statistik verfügbar (noch keine Ziehungen).
          </p>
        </UCard>

        <UCard
          v-else-if="lotto.selectedGame.value?.kind === 'digit'"
          :ui="{ body: 'p-0' }"
        >
          <template #header>
            <div>
              <h4 class="text-sm font-semibold text-default">
                Häufigkeit pro Position
              </h4>
              <div class="text-xs text-muted">
                über {{ lotto.stats.value.n }} Ziehung(en)
              </div>
            </div>
          </template>
          <div class="p-5 space-y-3">
            <div
              v-for="pp in (lotto.stats.value.per_position || [])"
              :key="pp.position"
            >
              <div class="text-xs text-muted mb-1">
                Position {{ pp.position + 1 }}
              </div>
              <div class="flex items-end gap-1 h-12">
                <div
                  v-for="f in pp.frequency"
                  :key="f.digit"
                  class="flex-1 flex flex-col items-center gap-0.5"
                >
                  <div
                    class="w-full bg-primary/60 rounded-sm"
                    :style="{
                      height: `${(f.count / statsMaxCount(pp.frequency)) * 100}%`,
                      minHeight: '2px',
                    }"
                    :title="`Ziffer ${f.digit}: ${f.count}×`"
                  />
                  <span class="text-[10px] text-muted font-mono">{{ f.digit }}</span>
                </div>
              </div>
            </div>
          </div>
        </UCard>

        <UCard v-else :ui="{ body: 'p-0' }">
          <template #header>
            <div>
              <h4 class="text-sm font-semibold text-default">
                Frequenz: {{ statsMainPool(lotto.selectedGame.value)?.name }}
              </h4>
              <div class="text-xs text-muted">
                über {{ lotto.stats.value.n }} Ziehung(en) · Erwartet pro Zahl: ~{{
                  Math.round(
                    (lotto.stats.value.n
                      * (statsMainPool(lotto.selectedGame.value)?.pick || 1))
                      / Math.max(1, (statsMainPool(lotto.selectedGame.value)?.high || 1)
                        - (statsMainPool(lotto.selectedGame.value)?.low || 1) + 1),
                  )
                }}×
              </div>
            </div>
          </template>
          <div class="p-5">
            <div class="grid grid-cols-7 gap-1">
              <div
                v-for="row in statsMainData(lotto.selectedGame.value)"
                :key="row.number"
                class="text-center text-xs font-mono py-1 rounded"
                :style="{
                  background: `rgba(56, 189, 248, ${0.15 + (row.count / statsMaxCount(statsMainData(lotto.selectedGame.value))) * 0.7})`,
                  color: (row.count / statsMaxCount(statsMainData(lotto.selectedGame.value))) > 0.6 ? '#0b1220' : undefined,
                }"
                :title="`${row.number}: ${row.count}× (Gap ${row.gap})`"
              >
                {{ String(row.number).padStart(2, '0') }}
              </div>
            </div>
            <div class="mt-3 text-xs text-muted">
              Helle Felder = häufiger gezogen. Hover für genaue Zählung +
              aktuelle Pause (Gap) seit letzter Ziehung.
            </div>
          </div>
        </UCard>
      </div>

      <!-- Full-width: Charts + Jackpot-Backtest -->
      <div class="lg:col-span-3 grid lg:grid-cols-2 gap-6">
        <LottoCharts />
        <JackpotBacktestPanel :game-id="lotto.selectedId.value" />
      </div>
    </div>

    <!-- Loading-Skeleton (initial) -->
    <div v-else-if="lotto.overviewLoading.value" class="animate-pulse space-y-4">
      <div class="h-32 bg-elevated rounded-xl" />
      <div class="h-64 bg-elevated rounded-xl" />
    </div>
  </div>
</template>

