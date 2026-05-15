<!--
  Phase-3-Smoke-Page: rendert den App-Shell mit echten Daten aus dem
  Pinia-Store (useSystemStatus). Zeigt KPI-Strip, Service-Liste und
  GPU/Memory — die richtige Dashboard-Page kommt in Phase 4 Welle A.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'

definePageMeta({
  layout: 'default',
})

const store = useSystemStore()
const { status, loading, error, lastUpdated } = storeToRefs(store)

const services = computed(() => status.value?.services ?? [])
const deployed = computed(() => services.value.filter(s => s.status !== 'not_deployed'))
const healthyCount = computed(() => deployed.value.filter(s => s.status === 'healthy').length)
const degradedCount = computed(() => deployed.value.filter(s => s.status === 'degraded').length)

const lastUpdatedLabel = computed(() => {
  if (!lastUpdated.value) return '—'
  const seconds = Math.floor((Date.now() - lastUpdated.value) / 1000)
  return `vor ${seconds}s`
})

function statusColor(s: string) {
  if (s === 'healthy') return 'success'
  if (s === 'degraded') return 'warning'
  if (s === 'unhealthy' || s === 'failed') return 'error'
  return 'neutral'
}
</script>

<template>
  <div class="space-y-6 p-6 md:p-10">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-default">
          Dashboard
        </h1>
        <p class="text-sm text-muted">
          Phase-3-Stub — App-Shell + Live-Polling. Vollausbau folgt in Phase 4 Welle A.
        </p>
      </div>
      <UBadge color="neutral" variant="subtle">
        Aktualisiert {{ lastUpdatedLabel }}
      </UBadge>
    </header>

    <UAlert
      v-if="error"
      color="error"
      variant="subtle"
      icon="i-lucide-alert-triangle"
      title="Status konnte nicht geladen werden"
      :description="error"
    />

    <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
      <UCard>
        <p class="text-xs font-semibold uppercase tracking-widest text-muted">
          Services
        </p>
        <p class="mt-1 text-3xl font-bold text-default">
          {{ healthyCount }}<span class="text-base text-muted"> / {{ deployed.length }}</span>
        </p>
        <p class="mt-1 text-xs text-muted">
          {{ degradedCount }} degraded
        </p>
      </UCard>
      <UCard>
        <p class="text-xs font-semibold uppercase tracking-widest text-muted">
          GPU
        </p>
        <p class="mt-1 truncate text-lg font-semibold text-default">
          {{ status?.gpu?.name ?? '—' }}
        </p>
        <p class="mt-1 text-xs text-muted">
          {{ status?.gpu?.gpu_count ?? 1 }} ×
          {{ status?.gpu?.memoryType ?? 'discrete' }}
        </p>
      </UCard>
      <UCard>
        <p class="text-xs font-semibold uppercase tracking-widest text-muted">
          Tier · Backend
        </p>
        <p class="mt-1 text-lg font-semibold text-default">
          {{ status?.tier ?? '—' }}
        </p>
        <p class="mt-1 text-xs text-muted">
          v{{ status?.version ?? '0.0.0' }}
        </p>
      </UCard>
    </div>

    <UCard>
      <template #header>
        <div class="flex items-center justify-between">
          <h2 class="font-semibold text-default">
            Service-Inventar
          </h2>
          <UBadge variant="outline">
            {{ services.length }}
          </UBadge>
        </div>
      </template>
      <USkeleton v-if="loading && !services.length" class="h-32" />
      <ul v-else class="divide-y divide-default">
        <li
          v-for="svc in services"
          :key="svc.id || svc.name"
          class="flex items-center justify-between py-2.5 text-sm"
        >
          <div class="min-w-0 flex-1">
            <p class="font-medium text-default">
              {{ svc.name }}
            </p>
            <p class="truncate text-xs text-muted">
              {{ svc.id }}
            </p>
          </div>
          <UBadge :color="statusColor(svc.status)" variant="subtle" size="sm">
            {{ svc.status }}
          </UBadge>
        </li>
      </ul>
    </UCard>
  </div>
</template>

