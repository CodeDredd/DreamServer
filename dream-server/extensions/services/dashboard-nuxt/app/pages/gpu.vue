<!--
  GPU-Monitor (Phase 4 Welle A.2). Funktional pendant zu
  dashboard/src/pages/GPUMonitor.jsx (166 LoC) — zeigt Aggregat-Strip,
  Per-GPU-Cards, optional Topology + History (5s-Polling).
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useGpuDetailed } from '~/composables/useGpuDetailed'
definePageMeta({ layout: 'default' })
const { detailed, history, topology, loading, error } = useGpuDetailed()
interface DetailedGpu {
  index: number
  name: string
  vendor?: string
  vramTotal: number
  vramUsed: number
  utilization: number
  temperature: number
  powerDraw?: number
  powerLimit?: number
}
interface Aggregate {
  name?: string
  utilization_percent?: number
  memory_used_mb?: number
  memory_total_mb?: number
  power_draw_w?: number
  power_limit_w?: number
}
const gpus = computed<DetailedGpu[]>(() => (detailed.value as { gpus?: DetailedGpu[] } | null)?.gpus ?? [])
const backend = computed(() => (detailed.value as { backend?: string } | null)?.backend ?? '—')
const gpuCount = computed(() => (detailed.value as { gpu_count?: number } | null)?.gpu_count ?? gpus.value.length)
const aggregate = computed<Aggregate | null>(
  () => (detailed.value as { aggregate?: Aggregate } | null)?.aggregate ?? null,
)
function pctColor(p: number): 'success' | 'warning' | 'error' {
  if (p > 90) return 'error'
  if (p > 70) return 'warning'
  return 'success'
}
function tempColor(t: number): 'success' | 'warning' | 'error' {
  if (t >= 85) return 'error'
  if (t >= 70) return 'warning'
  return 'success'
}
</script>
<template>
  <UDashboardPanel id="gpu-monitor">
    <template #header>
      <UDashboardNavbar
        title="GPU Monitor"
        :description="`${gpuCount} GPU${gpuCount === 1 ? '' : 's'} · ${backend.toString().toUpperCase()}`"
        icon="i-lucide-activity"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UBadge color="primary" variant="subtle" icon="i-lucide-refresh-cw" size="sm">
            live · 5s
          </UBadge>
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <div class="space-y-6">
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-alert-triangle"
          title="GPU-Daten nicht verfügbar"
          :description="error"
        />
        <div v-if="loading && !gpus.length" class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <USkeleton v-for="n in 4" :key="n" class="h-44 rounded-xl" />
        </div>
        <!-- Aggregate strip (only if multiple GPUs) -->
        <UCard v-if="aggregate && gpuCount > 1">
          <template #header>
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold uppercase tracking-widest text-muted">
                Aggregate
              </h2>
              <span class="text-xs text-muted">{{ aggregate.name }}</span>
            </div>
          </template>
          <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
            <div>
              <p class="text-[10px] uppercase tracking-widest text-muted">Avg Util</p>
              <p class="font-mono text-lg text-default">{{ aggregate.utilization_percent }} %</p>
              <UProgress
                class="mt-1"
                :model-value="aggregate.utilization_percent ?? 0"
                size="xs"
                :color="pctColor(aggregate.utilization_percent ?? 0)"
              />
            </div>
            <div>
              <p class="text-[10px] uppercase tracking-widest text-muted">Total VRAM</p>
              <p class="font-mono text-lg text-default">
                {{ ((aggregate.memory_used_mb ?? 0) / 1024).toFixed(1) }} /
                {{ ((aggregate.memory_total_mb ?? 0) / 1024).toFixed(0) }} GB
              </p>
            </div>
            <div v-if="aggregate.power_draw_w != null">
              <p class="text-[10px] uppercase tracking-widest text-muted">Power</p>
              <p class="font-mono text-lg text-default">
                {{ aggregate.power_draw_w?.toFixed(0) }} /
                {{ aggregate.power_limit_w?.toFixed(0) ?? '—' }} W
              </p>
            </div>
          </div>
        </UCard>
        <!-- Per-GPU cards -->
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <UPageCard
            v-for="g in gpus"
            :key="g.index"
            :title="g.name"
            :description="`GPU ${g.index} · ${g.vendor ?? backend}`"
            icon="i-lucide-cpu"
            variant="subtle"
          >
            <div class="space-y-3">
              <div>
                <div class="flex items-center justify-between text-xs text-muted">
                  <span>Util</span>
                  <span class="font-mono text-default">{{ g.utilization }} %</span>
                </div>
                <UProgress
                  :model-value="g.utilization"
                  size="xs"
                  :color="pctColor(g.utilization)"
                />
              </div>
              <div>
                <div class="flex items-center justify-between text-xs text-muted">
                  <span>VRAM</span>
                  <span class="font-mono text-default">
                    {{ (g.vramUsed / 1024).toFixed(1) }} / {{ (g.vramTotal / 1024).toFixed(0) }} GB
                  </span>
                </div>
                <UProgress
                  :model-value="g.vramTotal > 0 ? (g.vramUsed / g.vramTotal) * 100 : 0"
                  size="xs"
                  :color="pctColor(g.vramTotal > 0 ? (g.vramUsed / g.vramTotal) * 100 : 0)"
                />
              </div>
              <div class="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p class="text-muted">Temp</p>
                  <p class="font-mono text-default">
                    <span :class="`text-${tempColor(g.temperature)}`">{{ g.temperature }}°C</span>
                  </p>
                </div>
                <div v-if="g.powerDraw != null">
                  <p class="text-muted">Power</p>
                  <p class="font-mono text-default">
                    {{ g.powerDraw.toFixed(0) }}<span v-if="g.powerLimit"> / {{ g.powerLimit.toFixed(0) }}</span> W
                  </p>
                </div>
              </div>
            </div>
          </UPageCard>
        </div>
        <!-- Raw data debug toggle -->
        <UCard v-if="topology || history">
          <template #header>
            <h2 class="text-sm font-semibold text-default">Topology / History (raw)</h2>
          </template>
          <UCollapsible>
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-chevron-down"
              label="JSON anzeigen"
              size="sm"
            />
            <template #content>
              <pre class="mt-3 max-h-64 overflow-auto rounded bg-elevated p-3 text-[11px] text-muted">{{ JSON.stringify({ topology, history }, null, 2) }}</pre>
            </template>
          </UCollapsible>
        </UCard>
      </div>
    </template>
  </UDashboardPanel>
</template>
