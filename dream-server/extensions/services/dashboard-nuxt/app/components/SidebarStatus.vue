<!--
  Sidebar-Footer. Zeigt System-Health (Service-Counts), Speicher-Bar
  (unified vs discrete), Versions-Update-Hinweis und einen Color-Mode
  Toggle. Alles reaktiv ueber System-Store + Repository.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRepo } from 'pinia-orm'
import Service from '~~/store/models/Service'
import { useSystemStore } from '~/stores/system'
import { useVersion } from '~/composables/useVersion'

defineProps<{
  collapsed?: boolean
}>()

const store = useSystemStore()
const { status } = storeToRefs(store)
const { updateAvailable, version, dismissUpdate } = useVersion()

const services = computed(() => useRepo(Service).all())
const healthyCount = computed(() => services.value.filter(s => s.status === 'healthy').length)
const totalDeployed = computed(() => services.value.filter(s => s.status !== 'not_deployed').length)

// Speicher-Bar: bei Halo-Strix-Class (unified memory) RAM, sonst VRAM.
const memory = computed(() => {
  const gpu = status.value?.gpu
  const ram = status.value?.ram
  if (gpu?.memoryType === 'unified' && ram) {
    return {
      label: 'Unified',
      used: ram.used_gb,
      total: ram.total_gb,
      percent: ram.percent ?? Math.round((ram.used_gb / Math.max(ram.total_gb, 1)) * 100),
    }
  }
  if (gpu) {
    const used = gpu.vramUsed / 1024
    const total = gpu.vramTotal / 1024
    return {
      label: 'VRAM',
      used,
      total,
      percent: Math.round((used / Math.max(total, 0.1)) * 100),
    }
  }
  return null
})

function memoryColor(pct: number): 'success' | 'warning' | 'error' {
  if (pct >= 90) return 'error'
  if (pct >= 75) return 'warning'
  return 'success'
}
</script>

<template>
  <div class="flex flex-col gap-3 px-1">
    <!-- Update-Verfuegbar -->
    <UAlert
      v-if="updateAvailable && !collapsed"
      color="primary"
      variant="subtle"
      icon="i-lucide-arrow-up-circle"
      :title="`Update: ${version?.latest}`"
      :close="true"
      :ui="{ root: 'p-2', title: 'text-xs', wrapper: 'gap-1' }"
      @close="dismissUpdate"
    />

    <!-- Memory-Bar -->
    <div v-if="memory && !collapsed" class="flex flex-col gap-1">
      <div class="flex items-center justify-between text-[10px] uppercase tracking-widest text-muted">
        <span>{{ memory.label }}</span>
        <span>{{ memory.used.toFixed(1) }} / {{ memory.total.toFixed(0) }} GB</span>
      </div>
      <UProgress
        :model-value="memory.percent"
        :max="100"
        size="xs"
        :color="memoryColor(memory.percent)"
      />
    </div>

    <!-- Health + ColorMode -->
    <div class="flex items-center justify-between gap-2">
      <UTooltip v-if="!collapsed" :text="`${healthyCount} healthy / ${totalDeployed} deployed`">
        <UBadge
          :color="healthyCount === totalDeployed ? 'success' : 'warning'"
          variant="subtle"
          icon="i-lucide-heart-pulse"
          size="sm"
        >
          {{ healthyCount }}/{{ totalDeployed }}
        </UBadge>
      </UTooltip>
      <UTooltip v-else :text="`${healthyCount}/${totalDeployed} healthy`">
        <UIcon
          name="i-lucide-heart-pulse"
          class="size-4"
          :class="healthyCount === totalDeployed ? 'text-success' : 'text-warning'"
        />
      </UTooltip>
      <ClientOnly>
        <ColorModeButton />
      </ClientOnly>
    </div>
  </div>
</template>

