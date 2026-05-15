<!--
  Models-Page (Phase 4 Welle A.3). Pendant zu
  dashboard/src/pages/Models.jsx (347 LoC). Listet Modelle, zeigt
  VRAM-Indikator, erlaubt Download/Load/Delete + Live-Progress aus
  useDownloadProgress.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useModels } from '~/composables/useModels'
import { useDownloadProgress } from '~/composables/useDownloadProgress'

definePageMeta({ layout: 'default' })

const {
  models,
  gpu,
  currentModel,
  loading,
  error,
  actionLoading,
  download,
  load,
  delete: deleteModel,
  refresh,
} = useModels()
const dl = useDownloadProgress()

const vramPercent = computed(() => {
  const g = gpu.value
  if (!g || !g.vramTotal) return 0
  return (g.vramUsed / g.vramTotal) * 100
})

function vramColor(p: number): 'success' | 'warning' | 'error' {
  if (p > 90) return 'error'
  if (p > 70) return 'warning'
  return 'success'
}
function statusColor(s: string): 'success' | 'warning' | 'neutral' | 'primary' {
  if (s === 'loaded') return 'success'
  if (s === 'downloading') return 'primary'
  if (s === 'error') return 'warning'
  return 'neutral'
}
function statusLabel(s: string): string {
  if (s === 'loaded') return 'aktiv'
  if (s === 'downloaded' || s === 'available') return 'verfügbar'
  if (s === 'downloading') return 'lädt…'
  return s
}
</script>

<template>
  <UDashboardPanel id="models">
    <template #header>
      <UDashboardNavbar
        title="Models"
        description="Download, Switch und Verwaltung lokaler AI-Modelle"
        icon="i-lucide-box"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-refresh-cw"
            size="sm"
            :loading="loading"
            @click="refresh"
          />
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
          title="Fehler beim Laden"
          :description="error"
        />
        <!-- Live download progress -->
        <UCard v-if="dl.isDownloading.value">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-semibold text-default">
                Download: {{ dl.modelName.value || dl.modelId.value }}
              </p>
              <p class="text-xs text-muted">
                {{ dl.speedMbps.value?.toFixed(1) ?? '0' }} MB/s · ETA
                {{ dl.eta.value ?? '—' }}s
              </p>
            </div>
            <span class="font-mono text-lg text-primary">
              {{ (dl.percent.value ?? 0).toFixed(1) }} %
            </span>
          </div>
          <UProgress
            class="mt-2"
            :model-value="dl.percent.value ?? 0"
            color="primary"
            size="sm"
          />
        </UCard>
        <!-- VRAM indicator -->
        <UCard v-if="gpu">
          <div class="flex items-center justify-between text-xs text-muted">
            <span>GPU VRAM</span>
            <span class="font-mono text-default">
              {{ gpu.vramUsed.toFixed(1) }} / {{ gpu.vramTotal.toFixed(0) }} GB used
            </span>
          </div>
          <UProgress
            class="mt-2"
            :model-value="vramPercent"
            size="sm"
            :color="vramColor(vramPercent)"
          />
          <p class="mt-2 text-xs text-muted">
            {{ gpu.vramFree.toFixed(1) }} GB frei · grüne Badges = passt in dein VRAM
          </p>
        </UCard>
        <!-- Models list -->
        <div v-if="loading && !models.length" class="space-y-3">
          <USkeleton v-for="n in 3" :key="n" class="h-28 rounded-xl" />
        </div>
        <div v-else class="space-y-3">
          <UCard
            v-for="m in models"
            :key="m.id"
            :ui="{ root: m.id === currentModel ? 'ring-2 ring-success/40' : '' }"
          >
            <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <h3 class="text-base font-semibold text-default">
                    {{ m.name }}
                  </h3>
                  <UBadge :color="statusColor(m.status)" variant="subtle" size="sm">
                    {{ statusLabel(m.status) }}
                  </UBadge>
                  <UBadge
                    v-if="m.fitsVram"
                    color="success"
                    variant="subtle"
                    icon="i-lucide-check"
                    size="sm"
                  >
                    passt
                  </UBadge>
                  <UBadge v-else color="neutral" variant="subtle" size="sm">
                    {{ m.vramRequired }} GB VRAM
                  </UBadge>
                </div>
                <p v-if="m.description" class="mt-1 text-xs text-muted">
                  {{ m.description }}
                </p>
                <div class="mt-2 flex flex-wrap gap-3 font-mono text-[11px] text-muted">
                  <span>{{ m.size }}</span>
                  <span v-if="m.contextLength">ctx {{ (m.contextLength / 1024).toFixed(0) }}k</span>
                  <span v-if="m.tokensPerSec">{{ m.tokensPerSec }} tok/s</span>
                  <span v-if="m.quantization">{{ m.quantization }}</span>
                </div>
              </div>
              <div class="flex shrink-0 items-center gap-2">
                <UButton
                  v-if="m.status === 'available'"
                  color="primary"
                  variant="solid"
                  icon="i-lucide-download"
                  size="sm"
                  label="Download"
                  :loading="actionLoading === m.id"
                  @click="download(m.id)"
                />
                <UButton
                  v-else-if="m.status === 'downloaded' && m.id !== currentModel"
                  color="primary"
                  variant="solid"
                  icon="i-lucide-play"
                  size="sm"
                  label="Load"
                  :loading="actionLoading === m.id"
                  @click="load(m.id)"
                />
                <UButton
                  v-if="m.status === 'downloaded' || m.status === 'loaded'"
                  color="neutral"
                  variant="ghost"
                  icon="i-lucide-trash-2"
                  size="sm"
                  square
                  :loading="actionLoading === m.id"
                  :disabled="m.id === currentModel"
                  :title="m.id === currentModel ? 'Aktives Modell zuerst entladen' : 'Löschen'"
                  @click="deleteModel(m.id)"
                />
              </div>
            </div>
          </UCard>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>

