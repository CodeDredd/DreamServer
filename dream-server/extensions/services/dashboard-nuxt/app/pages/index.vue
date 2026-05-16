<!--
  Dashboard-Startseite (Phase 4 Welle A). Dreigeteilt:
    1. KpiStrip      - System-Metrik-Tiles (GPU/RAM/CPU/Power/Temp/...).
    2. FeatureCards  - /api/features Cards mit external-link wenn ready.
    3. ServicesGrid  - Live-Service-Liste mit Tab-Filter + per-Container
                       CPU/Mem aus /api/services/resources.
  React-Pendant: dashboard/src/pages/Dashboard.jsx (1480 LoC).
  Visuelle 1:1-Paritaet ist nicht das Ziel - Phase 4 liefert
  funktionale Paritaet im Nuxt-UI-v4-Look. Tech-tiles, Liquid-Metal-
  Frames und der Custom-System-Overview-Chart wandern in Welle A.2,
  falls noetig.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRepo } from 'pinia-orm'
import Service from '~~/store/models/Service'
import { useSystemStore } from '~/stores/system'
import SpielscheinGenerator from '~/components/finance-guru/SpielscheinGenerator.vue'
import { useLotto } from '~/composables/useLotto'
definePageMeta({ layout: 'default' })
const store = useSystemStore()
const { status, error, lastUpdated } = storeToRefs(store)
const services = computed(() => useRepo(Service).all())
const deployed = computed(() => services.value.filter(s => s.status !== 'not_deployed'))
const healthyCount = computed(() => deployed.value.filter(s => s.status === 'healthy').length)
const allHealthy = computed(() => deployed.value.length > 0 && healthyCount.value === deployed.value.length)
const lottoComposable = useLotto()
const lottoAvailable = computed(() => !!lottoComposable.status.value?.available)
const lastUpdatedLabel = computed(() => {
  if (!lastUpdated.value) return '-'
  const sec = Math.floor((Date.now() - lastUpdated.value) / 1000)
  return `vor ${sec}s`
})
const healthLabel = computed(() => {
  if (!deployed.value.length) return 'Warte auf Telemetrie…'
  return `${healthyCount.value}/${deployed.value.length} Services online`
})
</script>
<template>
  <UDashboardPanel id="dashboard-home">
    <template #header>
      <UDashboardNavbar
        title="Dashboard"
        :description="healthLabel"
        icon="i-lucide-layout-dashboard"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <div class="hidden items-center gap-2 font-mono text-[11px] text-muted md:flex">
            <span v-if="status?.tier" class="text-primary">{{ status.tier }}</span>
            <span v-if="status?.model?.name">· {{ status.model.name }}</span>
            <span v-if="status?.version">· v{{ status.version }}</span>
          </div>
          <UBadge
            :color="allHealthy ? 'success' : 'warning'"
            variant="subtle"
            icon="i-lucide-heart-pulse"
            size="sm"
          >
            {{ lastUpdatedLabel }}
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
        <DashboardKpiStrip />
        <DashboardFeatureCards />
        <DashboardServicesGrid />
        <SpielscheinGenerator v-if="lottoAvailable" />
      </div>
    </template>
  </UDashboardPanel>
</template>
