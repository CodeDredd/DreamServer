<!--
  Settings (Phase 4 Welle A.4 — Skinny Port). Pendant zu
  dashboard/src/pages/Settings.jsx (291 LoC + EnvEditor 1000+ LoC).

  Welle A liefert die Status-Seite mit:
  * Version-Card (current/latest, Update-Badge, dismiss/apply)
  * Storage-Snapshot (gesamt + per-Service)
  * Service-Restart-Buttons
  Der vollwertige Env-Editor bleibt fuer Welle A.5 reserviert — er ist
  allein groesser als alle anderen Welle-A-Pages zusammen.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'
import { useVersion, triggerUpdate } from '~/composables/useVersion'
import { useServiceResources } from '~/composables/useServiceResources'
import { useApi } from '~/composables/useApi'

definePageMeta({ layout: 'default' })

const sys = useSystemStore()
const { status } = storeToRefs(sys)
const { version, updateAvailable, dismissUpdate, refresh: refreshVersion } = useVersion()
const { resources } = useServiceResources()
const api = useApi()

const restartLoading = ref<string | null>(null)
const restartError = ref<string | null>(null)
const updateLoading = ref(false)

const totalDiskGb = computed(() => status.value?.disk?.used_gb ?? 0)
const totalDiskCapacityGb = computed(() => status.value?.disk?.total_gb ?? 0)
const diskPercent = computed(() => status.value?.disk?.percent ?? 0)

const restartable = computed(() =>
  resources.value
    .filter(r => r.restartable && r.container)
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name)),
)

async function restartService(id: string) {
  restartLoading.value = id
  restartError.value = null
  try {
    await api.post(`/api/services/${encodeURIComponent(id)}/restart`)
  }
  catch (err: unknown) {
    restartError.value = `${id}: ${(err as Error).message}`
  }
  finally {
    restartLoading.value = null
  }
}

async function runUpdate(action: string) {
  updateLoading.value = true
  try {
    await triggerUpdate(action)
    await refreshVersion()
  }
  finally {
    updateLoading.value = false
  }
}

function diskColor(p: number): 'success' | 'warning' | 'error' {
  if (p >= 90) return 'error'
  if (p >= 75) return 'warning'
  return 'success'
}
</script>

<template>
  <UDashboardPanel id="settings">
    <template #header>
      <UDashboardNavbar
        title="Settings"
        description="System-Status, Updates und Service-Restart"
        icon="i-lucide-settings"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <div class="space-y-6">
        <!-- Version + Update -->
        <UCard>
          <template #header>
            <h2 class="text-base font-semibold text-default">
              Version
            </h2>
          </template>
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="font-mono text-sm">
              <p class="text-default">
                Aktuell: <span class="text-primary">v{{ version?.current ?? '?' }}</span>
              </p>
              <p v-if="version?.latest" class="text-muted">
                Latest: v{{ version.latest }}
              </p>
            </div>
            <div class="flex items-center gap-2">
              <UBadge v-if="updateAvailable" color="primary" variant="subtle" icon="i-lucide-arrow-up-circle">
                Update verfügbar
              </UBadge>
              <UButton
                color="primary"
                variant="solid"
                icon="i-lucide-download"
                size="sm"
                label="Update jetzt"
                :loading="updateLoading"
                :disabled="!updateAvailable"
                @click="runUpdate('apply')"
              />
              <UButton
                v-if="updateAvailable"
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                size="sm"
                square
                title="Update-Hinweis verbergen"
                @click="dismissUpdate"
              />
            </div>
          </div>
          <p v-if="version?.release_notes" class="mt-3 max-h-40 overflow-auto rounded bg-elevated p-3 text-xs text-muted">
            {{ version.release_notes }}
          </p>
        </UCard>

        <!-- Storage -->
        <UCard>
          <template #header>
            <div class="flex items-center justify-between">
              <h2 class="text-base font-semibold text-default">
                Storage
              </h2>
              <span class="font-mono text-xs text-muted">
                {{ totalDiskGb.toFixed(1) }} / {{ totalDiskCapacityGb.toFixed(0) }} GB
              </span>
            </div>
          </template>
          <UProgress :model-value="diskPercent" size="sm" :color="diskColor(diskPercent)" />
          <div class="mt-4 space-y-2">
            <div
              v-for="r in resources.filter(x => x.disk)"
              :key="r.id"
              class="flex items-center justify-between text-xs"
            >
              <span class="truncate text-default">{{ r.name }}</span>
              <span class="font-mono text-muted">
                {{ r.disk?.data_gb.toFixed(2) }} GB
                <span class="ml-1 text-[10px]">{{ r.disk?.path }}</span>
              </span>
            </div>
          </div>
        </UCard>

        <!-- Service Restart -->
        <UCard>
          <template #header>
            <h2 class="text-base font-semibold text-default">
              Services neustarten
            </h2>
          </template>
          <UAlert
            v-if="restartError"
            color="error"
            variant="subtle"
            icon="i-lucide-alert-triangle"
            class="mb-3"
            :description="restartError"
          />
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <UButton
              v-for="r in restartable"
              :key="r.id"
              :loading="restartLoading === r.id"
              :disabled="restartLoading !== null && restartLoading !== r.id"
              color="neutral"
              variant="outline"
              icon="i-lucide-rotate-cw"
              size="sm"
              :label="r.name"
              class="justify-start"
              @click="restartService(r.id)"
            />
          </div>
        </UCard>

        <UAlert
          color="primary"
          variant="subtle"
          icon="i-lucide-info"
          title="Environment-Editor folgt in Welle A.5"
          description="Der vollwertige .env-Editor (Sektionen, Reveal-Secrets, Apply-Plan, Routes-Map) wird separat migriert — er ist groesser als alle anderen Welle-A-Pages zusammen."
        />
      </div>
    </template>
  </UDashboardPanel>
</template>
