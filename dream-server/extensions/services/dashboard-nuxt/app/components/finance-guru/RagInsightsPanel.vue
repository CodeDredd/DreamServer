<!--
  Phase F: RagInsightsPanel — drei Collapsibles, je eine RAG-Collection:
    * finance_relations          (Causal-Themes, Phase E)
    * finance_asset_analysis     (Symbol-Behaviour, Phase A.2/B)
    * finance_strategy_lessons   (Was haben gescheiterte Strategien gelehrt)

  Pro Collapsible:
    - Suchfeld (debounced via UInput v-model + Submit)
    - Submit-Button (oder Enter im Input)
    - Hit-Liste, kompakt; Klick auf Hit öffnet UModal mit Volltext.

  Bewusst KEINE polling-getriebene Datenquelle — RAG-Queries kosten
  Embedding-Calls, also nur auf User-Aktion.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useFinanceGuru } from '~/composables/useFinanceGuru'
import { formatPct, pnlToneClass, relTime } from '~/utils/format'
import type {
  FinanceAnalysisHit,
  FinanceLessonHit,
  FinanceRelationHit,
} from '~/types/api'

const fg = useFinanceGuru()

// ---- Relations -----------------------------------------------------------
const relQuery = ref('macro themes affecting tech this week')
const relHits = ref<FinanceRelationHit[]>([])
const relLoading = ref(false)
async function searchRelations() {
  if (relLoading.value) return
  relLoading.value = true
  try { relHits.value = await fg.searchRelations(relQuery.value, 8, 0.3) }
  finally { relLoading.value = false }
}

// ---- Analyses ------------------------------------------------------------
const anaQuery = ref('biggest sentiment drivers in the last week')
const anaHits = ref<FinanceAnalysisHit[]>([])
const anaLoading = ref(false)
async function searchAnalyses() {
  if (anaLoading.value) return
  anaLoading.value = true
  try { anaHits.value = await fg.searchAnalyses(anaQuery.value, 8, 0.4) }
  finally { anaLoading.value = false }
}

// ---- Strategy lessons ---------------------------------------------------
const lessonQuery = ref('why recent generated strategies were archived')
const lessonHits = ref<FinanceLessonHit[]>([])
const lessonLoading = ref(false)
async function searchLessons() {
  if (lessonLoading.value) return
  lessonLoading.value = true
  try { lessonHits.value = await fg.searchLessons(lessonQuery.value, 8) }
  finally { lessonLoading.value = false }
}

// ---- Modal: detail view of a single hit ---------------------------------
type DetailItem =
  | { kind: 'relation', hit: FinanceRelationHit }
  | { kind: 'analysis', hit: FinanceAnalysisHit }
  | { kind: 'lesson',   hit: FinanceLessonHit }
const showDetail = ref(false)
const detail = ref<DetailItem | null>(null)
function open(kind: DetailItem['kind'], hit: any) {
  detail.value = { kind, hit } as DetailItem
  showDetail.value = true
}
const detailTitle = computed(() => {
  if (!detail.value) return ''
  if (detail.value.kind === 'relation') return detail.value.hit.theme
  if (detail.value.kind === 'analysis') return detail.value.hit.symbol
  return detail.value.hit.strategy
})

// Folded-state for the three collapsibles. Default: relations open.
const open0 = ref(true)
const open1 = ref(false)
const open2 = ref(false)
</script>

<template>
  <UCard variant="subtle" :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-brain" class="size-4 text-primary" />
          <h3 class="text-sm font-semibold">
            RAG Insights
          </h3>
        </div>
        <span class="text-xs text-muted">
          Suchen kosten Embedding-Calls — daher manuell.
        </span>
      </div>
    </template>

    <div class="divide-y divide-default">
      <!-- ---------- Relations ---------------------------------------- -->
      <UCollapsible v-model:open="open0" :ui="{ trigger: 'w-full' }">
        <template #default>
          <div class="flex items-center justify-between gap-2 px-4 py-3 hover:bg-elevated/40 cursor-pointer">
            <div class="flex items-center gap-2">
              <UIcon name="i-lucide-network" class="size-3.5 text-muted" />
              <span class="text-sm font-medium">Causal Relations</span>
              <UBadge variant="subtle" size="xs" color="neutral">
                finance_relations
              </UBadge>
              <UBadge v-if="relHits.length" variant="subtle" size="xs" color="primary">
                {{ relHits.length }} hits
              </UBadge>
            </div>
            <UIcon :name="open0 ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
                   class="size-3.5 text-muted"
            />
          </div>
        </template>
        <template #content>
          <div class="space-y-3 border-t border-default bg-elevated/20 px-4 py-3">
            <div class="flex gap-2">
              <UInput v-model="relQuery"
                      placeholder="Welche Themen beeinflussen mehrere Symbole?"
                      icon="i-lucide-search"
                      size="sm" class="flex-1"
                      @keydown.enter="searchRelations"
              />
              <UButton color="primary" variant="subtle" size="sm"
                       :loading="relLoading" :disabled="!relQuery.trim()"
                       icon="i-lucide-arrow-right"
                       @click="searchRelations"
              >
                Suchen
              </UButton>
            </div>
            <div v-if="!relHits.length && !relLoading"
                 class="py-4 text-center text-xs text-muted"
            >
              Noch keine Suche ausgeführt.
            </div>
            <ul v-else-if="relHits.length" class="space-y-2">
              <li v-for="(h, i) in relHits" :key="i"
                  class="cursor-pointer rounded-md border border-default bg-default p-2 transition-colors hover:border-primary/50"
                  @click="open('relation', h)"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="truncate text-xs font-semibold text-default">
                        {{ h.theme }}
                      </span>
                      <UBadge v-if="h.confidence != null"
                              variant="subtle" size="xs"
                              :color="h.confidence >= 0.6 ? 'success'
                                : h.confidence >= 0.4 ? 'warning' : 'neutral'"
                      >
                        {{ Math.round(h.confidence * 100) }}%
                      </UBadge>
                    </div>
                    <div v-if="h.mechanism" class="mt-0.5 line-clamp-1 text-[11px] text-muted">
                      {{ h.mechanism }}
                    </div>
                    <div v-if="h.symbols?.length" class="mt-1 flex flex-wrap gap-1">
                      <UBadge v-for="s in h.symbols.slice(0, 8)" :key="s"
                              variant="outline" size="xs" color="neutral"
                              class="font-mono"
                      >
                        {{ s }}
                      </UBadge>
                    </div>
                  </div>
                  <span class="shrink-0 text-[10px] text-muted">{{ relTime(h.ts || '') }}</span>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </UCollapsible>

      <!-- ---------- Asset Analyses ---------------------------------- -->
      <UCollapsible v-model:open="open1" :ui="{ trigger: 'w-full' }">
        <template #default>
          <div class="flex items-center justify-between gap-2 px-4 py-3 hover:bg-elevated/40 cursor-pointer">
            <div class="flex items-center gap-2">
              <UIcon name="i-lucide-line-chart" class="size-3.5 text-muted" />
              <span class="text-sm font-medium">Asset Analyses</span>
              <UBadge variant="subtle" size="xs" color="neutral">
                finance_asset_analysis
              </UBadge>
              <UBadge v-if="anaHits.length" variant="subtle" size="xs" color="primary">
                {{ anaHits.length }} hits
              </UBadge>
            </div>
            <UIcon :name="open1 ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
                   class="size-3.5 text-muted"
            />
          </div>
        </template>
        <template #content>
          <div class="space-y-3 border-t border-default bg-elevated/20 px-4 py-3">
            <div class="flex gap-2">
              <UInput v-model="anaQuery"
                      placeholder="z.B. „mega-cap tech earnings reactions“"
                      icon="i-lucide-search" size="sm" class="flex-1"
                      @keydown.enter="searchAnalyses"
              />
              <UButton color="primary" variant="subtle" size="sm"
                       :loading="anaLoading" :disabled="!anaQuery.trim()"
                       icon="i-lucide-arrow-right" @click="searchAnalyses"
              >
                Suchen
              </UButton>
            </div>
            <div v-if="!anaHits.length && !anaLoading"
                 class="py-4 text-center text-xs text-muted"
            >
              Noch keine Suche ausgeführt.
            </div>
            <ul v-else-if="anaHits.length" class="space-y-2">
              <li v-for="(h, i) in anaHits" :key="i"
                  class="cursor-pointer rounded-md border border-default bg-default p-2 transition-colors hover:border-primary/50"
                  @click="open('analysis', h)"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="font-mono text-xs font-semibold">{{ h.symbol }}</span>
                      <UBadge v-if="h.confidence != null"
                              variant="subtle" size="xs"
                              :color="h.confidence >= 0.6 ? 'success'
                                : h.confidence >= 0.4 ? 'warning' : 'neutral'"
                      >
                        conf {{ Math.round(h.confidence * 100) }}%
                      </UBadge>
                    </div>
                    <div v-if="h.summary" class="mt-0.5 line-clamp-2 text-[11px] text-muted">
                      {{ h.summary }}
                    </div>
                  </div>
                  <span class="shrink-0 text-[10px] text-muted">{{ relTime(h.ts || '') }}</span>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </UCollapsible>

      <!-- ---------- Strategy Lessons -------------------------------- -->
      <UCollapsible v-model:open="open2" :ui="{ trigger: 'w-full' }">
        <template #default>
          <div class="flex items-center justify-between gap-2 px-4 py-3 hover:bg-elevated/40 cursor-pointer">
            <div class="flex items-center gap-2">
              <UIcon name="i-lucide-book-open" class="size-3.5 text-muted" />
              <span class="text-sm font-medium">Strategy Lessons</span>
              <UBadge variant="subtle" size="xs" color="neutral">
                finance_strategy_lessons
              </UBadge>
              <UBadge v-if="lessonHits.length" variant="subtle" size="xs" color="primary">
                {{ lessonHits.length }} hits
              </UBadge>
            </div>
            <UIcon :name="open2 ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
                   class="size-3.5 text-muted"
            />
          </div>
        </template>
        <template #content>
          <div class="space-y-3 border-t border-default bg-elevated/20 px-4 py-3">
            <div class="flex gap-2">
              <UInput v-model="lessonQuery"
                      placeholder="Was hat in der letzten Phase nicht funktioniert?"
                      icon="i-lucide-search" size="sm" class="flex-1"
                      @keydown.enter="searchLessons"
              />
              <UButton color="primary" variant="subtle" size="sm"
                       :loading="lessonLoading" :disabled="!lessonQuery.trim()"
                       icon="i-lucide-arrow-right" @click="searchLessons"
              >
                Suchen
              </UButton>
            </div>
            <div v-if="!lessonHits.length && !lessonLoading"
                 class="py-4 text-center text-xs text-muted"
            >
              Noch keine Suche ausgeführt.
            </div>
            <ul v-else-if="lessonHits.length" class="space-y-2">
              <li v-for="(h, i) in lessonHits" :key="i"
                  class="cursor-pointer rounded-md border border-default bg-default p-2 transition-colors hover:border-primary/50"
                  @click="open('lesson', h)"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="font-mono text-xs font-semibold">{{ h.strategy }}</span>
                      <UBadge v-if="h.outcome" variant="subtle" size="xs"
                              :color="h.outcome === 'promoted' ? 'success'
                                : h.outcome === 'retired' ? 'warning' : 'neutral'"
                      >
                        {{ h.outcome }}
                      </UBadge>
                      <UBadge v-if="h.pnl_pct != null"
                              variant="subtle" size="xs"
                              :color="(h.pnl_pct ?? 0) >= 0 ? 'success' : 'error'"
                      >
                        {{ formatPct(h.pnl_pct, 2) }}
                      </UBadge>
                    </div>
                    <div v-if="h.lesson" class="mt-0.5 line-clamp-2 text-[11px] text-muted">
                      {{ h.lesson }}
                    </div>
                  </div>
                  <span class="shrink-0 text-[10px] text-muted">{{ relTime(h.ts || '') }}</span>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </UCollapsible>
    </div>
  </UCard>

  <UModal v-model:open="showDetail" :title="detailTitle"
          :ui="{ content: 'max-w-2xl' }"
  >
    <template #body>
      <div v-if="detail?.kind === 'relation'" class="space-y-3 text-sm">
        <div v-if="detail.hit.mechanism">
          <div class="text-xs uppercase tracking-wider text-muted">Mechanism</div>
          <div class="mt-0.5">{{ detail.hit.mechanism }}</div>
        </div>
        <div v-if="detail.hit.summary">
          <div class="text-xs uppercase tracking-wider text-muted">Summary</div>
          <div class="mt-0.5 whitespace-pre-line">{{ detail.hit.summary }}</div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div v-if="detail.hit.symbols?.length">
            <div class="text-xs uppercase tracking-wider text-muted">Symbols</div>
            <div class="mt-1 flex flex-wrap gap-1">
              <UBadge v-for="s in detail.hit.symbols" :key="s"
                      variant="outline" size="xs" class="font-mono"
              >
                {{ s }}
              </UBadge>
            </div>
          </div>
          <div v-if="detail.hit.sectors?.length">
            <div class="text-xs uppercase tracking-wider text-muted">Sectors</div>
            <div class="mt-1 flex flex-wrap gap-1">
              <UBadge v-for="s in detail.hit.sectors" :key="s"
                      variant="subtle" size="xs" color="neutral"
              >
                {{ s }}
              </UBadge>
            </div>
          </div>
        </div>
        <div v-if="detail.hit.entities?.length">
          <div class="text-xs uppercase tracking-wider text-muted">Entities</div>
          <div class="mt-1 flex flex-wrap gap-1">
            <UBadge v-for="e in detail.hit.entities" :key="e"
                    variant="subtle" size="xs"
            >
              {{ e }}
            </UBadge>
          </div>
        </div>
        <div class="flex items-center gap-3 text-xs text-muted">
          <span v-if="detail.hit.confidence != null">
            confidence {{ Math.round(detail.hit.confidence * 100) }}%
          </span>
          <span v-if="detail.hit.ts">· {{ relTime(detail.hit.ts) }}</span>
          <span v-if="detail.hit.model">· model {{ detail.hit.model }}</span>
        </div>
      </div>
      <div v-else-if="detail?.kind === 'analysis'" class="space-y-3 text-sm">
        <div v-if="detail.hit.summary" class="whitespace-pre-line">
          {{ detail.hit.summary }}
        </div>
        <div v-if="detail.hit.keywords?.length" class="flex flex-wrap gap-1">
          <UBadge v-for="k in detail.hit.keywords" :key="k"
                  variant="subtle" size="xs" color="neutral"
          >
            {{ k }}
          </UBadge>
        </div>
        <div class="text-xs text-muted">
          <span v-if="detail.hit.confidence != null">
            confidence {{ Math.round(detail.hit.confidence * 100) }}%
          </span>
          <span v-if="detail.hit.ts">· {{ relTime(detail.hit.ts) }}</span>
        </div>
      </div>
      <div v-else-if="detail?.kind === 'lesson'" class="space-y-3 text-sm">
        <div v-if="detail.hit.lesson" class="whitespace-pre-line">
          {{ detail.hit.lesson }}
        </div>
        <div v-if="detail.hit.keywords?.length" class="flex flex-wrap gap-1">
          <UBadge v-for="k in detail.hit.keywords" :key="k"
                  variant="subtle" size="xs" color="neutral"
          >
            {{ k }}
          </UBadge>
        </div>
        <div class="flex items-center gap-3 text-xs text-muted">
          <span v-if="detail.hit.outcome">outcome: {{ detail.hit.outcome }}</span>
          <span v-if="detail.hit.pnl_pct != null"
                :class="pnlToneClass(detail.hit.pnl_pct)"
          >
            · PnL {{ formatPct(detail.hit.pnl_pct, 2) }}
          </span>
          <span v-if="detail.hit.ts">· {{ relTime(detail.hit.ts) }}</span>
        </div>
      </div>
    </template>
  </UModal>
</template>

