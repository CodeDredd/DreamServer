<!--
  Bootstrap-Banner — sichtbar wenn ein grosses Initial-Modell im
  Hintergrund laedt (LiteLLM/Lemonade Bootstrap auf Halo Strix).
  Daten aus useSystemStore().status.bootstrap.
-->
<script setup lang="ts">
import { computed } from 'vue'

interface BootstrapInfo {
  active?: boolean
  model?: string
  percent?: number
  speedMbps?: number
  eta?: number
  bytesDownloaded?: number
  bytesTotal?: number
}

const props = defineProps<{
  bootstrap: BootstrapInfo
}>()

function formatEta(seconds?: number) {
  if (!seconds || seconds <= 0) return 'calculating...'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${mins}m`
}

function formatGb(bytes?: number) {
  if (!bytes) return '0'
  return (bytes / 1e9).toFixed(1)
}

const percent = computed(() => Math.min(Math.max(props.bootstrap.percent || 0, 0), 100))
</script>

<template>
  <div class="border-b border-default bg-elevated px-4 py-3">
    <div class="mx-auto max-w-4xl">
      <div class="mb-2 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="size-2 animate-pulse rounded-full bg-primary" />
          <div>
            <p class="text-sm font-semibold text-default">
              Downloading Full Model
            </p>
            <p class="text-xs text-muted">
              Chat now with lightweight model
              <span v-if="bootstrap.model" class="text-primary">
                · {{ bootstrap.model }}
              </span>
            </p>
          </div>
        </div>
        <div class="text-right">
          <span class="text-xl font-bold text-primary">
            {{ percent.toFixed(1) }}%
          </span>
          <p v-if="bootstrap.speedMbps" class="text-xs text-muted">
            {{ bootstrap.speedMbps.toFixed(1) }} MB/s
          </p>
        </div>
      </div>
      <UProgress
        :model-value="percent"
        :max="100"
        size="sm"
        color="primary"
      />
      <p class="mt-2 text-xs text-muted">
        ETA: {{ formatEta(bootstrap.eta) }}
        · {{ formatGb(bootstrap.bytesDownloaded) }} / {{ formatGb(bootstrap.bytesTotal) }} GB
      </p>
    </div>
  </div>
</template>

