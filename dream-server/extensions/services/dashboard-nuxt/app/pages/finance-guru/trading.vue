<!--
  Finance Guru — Trading (Phase F).
  UTabs-Layout:
    • Overview  — KPI-Strip + Equity-Chart + Strategy-Liste/-Detail
                  (Positions & Trades in UCollapsible)
    • Lifecycle — StrategiesLifecyclePanel (live/proposed/archived/retired
                  + Leaderboard + Audit-Modal)
    • RAG       — RagInsightsPanel (relations / asset-analyses / lessons
                  via UCollapsible mit Inline-Suche + Detail-Modal)
    • Cycles    — CycleLogTable + EnrichmentRunsTable
  Header trägt: Refresh, Decide-Cycle, DSL-Catalog-Button (öffnet UModal).
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useFinanceGuru } from '~/composables/useFinanceGuru'
import { relTime } from '~/utils/format'
import StrategiesTab from '~/components/finance-guru/StrategiesTab.vue'
import StrategiesLifecyclePanel
  from '~/components/finance-guru/StrategiesLifecyclePanel.vue'
import RagInsightsPanel
  from '~/components/finance-guru/RagInsightsPanel.vue'
import CycleLogTable from '~/components/finance-guru/CycleLogTable.vue'
import EnrichmentRunsTable
  from '~/components/finance-guru/EnrichmentRunsTable.vue'

definePageMeta({ layout: 'default' })

const fg = useFinanceGuru()

const tab = ref<'overview' | 'lifecycle' | 'rag' | 'cycles'>('overview')

const strategyNames = computed(() => fg.strategies.value.map(s => s.name))

const tabItems = computed(() => [
  { value: 'overview',  label: 'Overview',
    icon: 'i-lucide-layout-dashboard',
    badge: fg.strategies.value.length || undefined },
  { value: 'lifecycle', label: 'Lifecycle',
    icon: 'i-lucide-git-branch',
    badge: fg.lifecycle.value.length || undefined },
  { value: 'rag',       label: 'RAG Insights',
    icon: 'i-lucide-brain',
    badge: undefined as number | undefined },
  { value: 'cycles',    label: 'Cycles & Runs',
    icon: 'i-lucide-history',
    badge: fg.cycleSummary.value?.last_24h || undefined },
])

const decideLoading = ref(false)
async function runDecide() {
  decideLoading.value = true
  try { await fg.decide(null) }
  finally { decideLoading.value = false }
}

const showCatalog = ref(false)

const scheduleLabel = computed(() => {
  const s = fg.schedule.value
  if (!s?.cron) return 'kein Cron'
  return `${s.cron} (${s.tz || 'UTC'})`
})
</script>

<template>
  <UDashboardPanel id="finance-guru-trading">
    <template #header>
      <UDashboardNavbar
        title="Finance Guru — Trading"
        icon="i-lucide-line-chart"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <div class="mr-2 hidden items-center gap-2 text-[11px] text-muted lg:flex">
            <span>{{ scheduleLabel }}</span>
            <span v-if="fg.nextRun.value">· next {{ relTime(fg.nextRun.value) }}</span>
          </div>
          <UTooltip text="DSL Catalog + Quota + Gate">
            <UButton color="neutral" variant="ghost" size="xs"
                     icon="i-lucide-book"
                     :disabled="!fg.dslCatalog.value"
                     @click="showCatalog = true"
            >
              DSL
            </UButton>
          </UTooltip>
          <UTooltip text="Refresh">
            <UButton color="neutral" variant="ghost" size="xs" square
                     icon="i-lucide-refresh-cw"
                     @click="fg.fetchAll()"
            />
          </UTooltip>
          <UButton color="primary" size="xs"
                   :icon="decideLoading ? 'i-lucide-loader-2' : 'i-lucide-play'"
                   :loading="decideLoading"
                   :disabled="decideLoading || !fg.status.value?.available"
                   @click="runDecide"
          >
            Decide cycle
          </UButton>
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <div class="space-y-4 p-4">
        <UTabs v-model="tab" :items="tabItems" variant="pill" color="primary" size="sm"
               :ui="{ list: 'w-full max-w-3xl', trigger: 'gap-2 text-xs' }"
        />
        <div v-if="tab === 'overview'">
          <StrategiesTab />
        </div>
        <div v-else-if="tab === 'lifecycle'">
          <StrategiesLifecyclePanel />
        </div>
        <div v-else-if="tab === 'rag'">
          <RagInsightsPanel />
        </div>
        <div v-else-if="tab === 'cycles'" class="space-y-4">
          <CycleLogTable :cycles="fg.cycles.value"
                         :summary="fg.cycleSummary.value"
                         :strategies="strategyNames"
          />
          <EnrichmentRunsTable :runs="fg.enrichmentRuns.value" />
        </div>
      </div>

      <!-- DSL catalog modal — heavy reference data out of the tab bar. -->
      <UModal v-model:open="showCatalog" title="DSL Catalog"
              description="Signals, Operators, Sizing, Limits, Gate + Genesis-Quota."
              :ui="{ content: 'max-w-3xl' }"
      >
        <template #body>
          <div v-if="!fg.dslCatalog.value" class="py-6 text-center text-sm text-muted">
            Catalog noch nicht geladen — finance-guru-api evtl. nicht erreichbar.
          </div>
          <div v-else class="space-y-4 text-sm">
            <section>
              <div class="mb-1 flex items-center gap-2">
                <UIcon name="i-lucide-shield" class="size-3.5 text-muted" />
                <h4 class="text-xs font-semibold uppercase tracking-wider text-muted">
                  Gate &amp; Quota
                </h4>
              </div>
              <div class="grid grid-cols-2 gap-2 md:grid-cols-4">
                <div class="rounded-md bg-elevated/40 p-2">
                  <div class="text-[10px] uppercase tracking-wider text-muted">min PnL %</div>
                  <div class="text-sm font-semibold tabular-nums">
                    {{ fg.dslCatalog.value.gate.min_backtest_pct }}
                  </div>
                </div>
                <div class="rounded-md bg-elevated/40 p-2">
                  <div class="text-[10px] uppercase tracking-wider text-muted">min Trades</div>
                  <div class="text-sm font-semibold tabular-nums">
                    {{ fg.dslCatalog.value.gate.min_backtest_trades }}
                  </div>
                </div>
                <div class="rounded-md bg-elevated/40 p-2">
                  <div class="text-[10px] uppercase tracking-wider text-muted">Backtest d</div>
                  <div class="text-sm font-semibold tabular-nums">
                    {{ fg.dslCatalog.value.gate.backtest_days }}
                  </div>
                </div>
                <div class="rounded-md bg-elevated/40 p-2">
                  <div class="text-[10px] uppercase tracking-wider text-muted">
                    Quota ({{ fg.dslCatalog.value.gate.quota_window_days }}d)
                  </div>
                  <div class="text-sm font-semibold tabular-nums">
                    {{ fg.dslCatalog.value.gate.quota_used }} /
                    {{ fg.dslCatalog.value.gate.quota_per_window }}
                  </div>
                </div>
              </div>
            </section>
            <section>
              <div class="mb-1 flex items-center gap-2">
                <UIcon name="i-lucide-list" class="size-3.5 text-muted" />
                <h4 class="text-xs font-semibold uppercase tracking-wider text-muted">
                  Signals ({{ Object.keys(fg.dslCatalog.value.signals).length }})
                </h4>
              </div>
              <ul class="max-h-72 space-y-1 overflow-y-auto rounded-md border border-default bg-elevated/20 p-2">
                <li v-for="(doc, name) in fg.dslCatalog.value.signals" :key="name" class="text-xs">
                  <code class="font-mono text-primary">{{ name }}</code>
                  <span class="ml-2 text-muted">{{ doc }}</span>
                </li>
              </ul>
            </section>
            <section class="grid gap-3 md:grid-cols-3">
              <div>
                <div class="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
                  Operators
                </div>
                <div class="flex flex-wrap gap-1">
                  <UBadge v-for="op in fg.dslCatalog.value.ops" :key="op"
                          variant="subtle" size="xs" color="neutral" class="font-mono"
                  >
                    {{ op }}
                  </UBadge>
                </div>
              </div>
              <div>
                <div class="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
                  Actions
                </div>
                <div class="flex flex-wrap gap-1">
                  <UBadge v-for="a in fg.dslCatalog.value.actions" :key="a"
                          variant="subtle" size="xs" color="primary"
                  >
                    {{ a }}
                  </UBadge>
                </div>
              </div>
              <div>
                <div class="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
                  Sizing
                </div>
                <div class="flex flex-wrap gap-1">
                  <UBadge v-for="s in fg.dslCatalog.value.sizing" :key="s"
                          variant="subtle" size="xs" color="info"
                  >
                    {{ s }}
                  </UBadge>
                </div>
              </div>
            </section>
            <section class="text-[11px] text-muted">
              limits: max {{ fg.dslCatalog.value.limits.max_rules }} rules ·
              {{ fg.dslCatalog.value.limits.max_predicates_per_rule }} predicates/rule ·
              max nesting {{ fg.dslCatalog.value.limits.max_nesting_depth }}
            </section>
          </div>
        </template>
      </UModal>
    </template>
  </UDashboardPanel>
</template>

