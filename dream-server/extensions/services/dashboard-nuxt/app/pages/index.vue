<!--
  Phase-3-Smoke-Page: rendert den App-Shell mit echten Daten aus dem
  System-Store (useSystemStatus). Zeigt KPI-Strip + Service-Inventar.
  Der Vollausbau folgt in Phase 4 Welle A (Cards/Charts).
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRepo } from 'pinia-orm'
import Service from '~~/store/models/Service'
import { useSystemStore } from '~/stores/system'
definePageMeta({ layout: 'default' })
const store = useSystemStore()
const { status, loading, error, lastUpdated } = storeToRefs(store)
// Service-Liste kommt aus dem ORM-Store (single source of truth).
const services = computed(() => useRepo(Service).orderBy('name').get())
const deployed = computed(() => services.value.filter(s => s.status !== 'not_deployed'))
const healthyCount = computed(() => deployed.value.filter(s => s.status === 'healthy').length)
const degradedCount = computed(() => deployed.value.filter(s => s.status === 'degraded').length)
const lastUpdatedLabel = computed(() => {
  if (!lastUpdated.value) return '-'
  const seconds = Math.floor((Date.now() - lastUpdated.value) / 1000)
  return `vor ${seconds}s`
})
function statusColor(s: string): 'success' | 'warning' | 'error' | 'neutral' {
  if (s === 'healthy') return 'success'
  if (s === 'degraded') return 'warning'
  if (s === 'unhealthy' || s === 'failed') return 'error'
  return 'neutral'
}
</script>
<template>
  <UDashboardPanel id="dashboard-home">
    <template #header>
      <UDashboardNavbar title="Dashboard" icon="i-lucide-layout-dashboard">
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UBadge color="neutral" variant="subtle">
            Aktualisiert {{ lastUpdatedLabel }}
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
          title="Status konnte nicht geladen werden"
          :description="error"
        />
        <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
          <UPageCard
            title="Services"
            :description="`${degradedCount} degraded`"
            icon="i-lucide-boxes"
            variant="subtle"
          >
            <p class="text-3xl font-bold text-default">
              {{ healthyCount }}<span class="text-base text-muted"> / {{ deployed.length }}</span>
            </p>
          </UPageCard>
          <UPageCard
            title="GPU"
            :description="`${status?.gpu?.gpu_count ?? 1} x ${status?.gpu?.memoryType ?? 'discrete'}`"
            icon="i-lucide-cpu"
            variant="subtle"
          >
            <p class="truncate text-lg font-semibold text-default">
              {{ status?.gpu?.name ?? '-' }}
            </p>
          </UPageCard>
          <UPageCard
            title="Tier / Backend"
            :description="`v${status?.version ?? '0.0.0'}`"
            icon="i-lucide-layers"
            variant="subtle"
          >
            <p class="text-lg font-semibold text-default">
              {{ status?.tier ?? '-' }}
            </p>
          </UPageCard>
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
  </UDashboardPanel>
</template>
