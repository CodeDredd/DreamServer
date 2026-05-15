<!--
  Sidebar fuer das Default-Layout. Nuxt-UI-v3-Variante des
  React-Sidebar.jsx.

  Sektionen (von oben):
    1. Logo + Version
    2. Navigation (UNavigationMenu, vertikal)
    3. Quick Links (externe Services, healthy = klickbar)
    4. Service-Statistik (online/total + degraded)
    5. Memory-Bar (RAM auf Halo Strix unified, sonst VRAM)
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '~/stores/ui'
import { useSystemStore } from '~/stores/system'
import { useDashboardRoutes } from '~/composables/useDashboardRoutes'
import { useExternalLinks } from '~/composables/useExternalLinks'

const ui = useUiStore()
const { sidebarCollapsed } = storeToRefs(ui)

const systemStore = useSystemStore()
const { status } = storeToRefs(systemStore)

const { visibleSidebar } = useDashboardRoutes()
const { links, visibleLinks } = useExternalLinks()
const showAllLinks = ref(false)

const navItems = computed(() => visibleSidebar.value.map(r => ({
  label: r.label,
  to: r.to,
  icon: r.icon,
})))

const externalShown = computed(() =>
  showAllLinks.value ? links.value : visibleLinks.value,
)

const services = computed(() => status.value?.services ?? [])
const deployed = computed(() => services.value.filter(s => s.status !== 'not_deployed'))
const onlineCount = computed(() =>
  deployed.value.filter(s => s.status === 'healthy' || s.status === 'degraded').length,
)
const degradedCount = computed(() =>
  deployed.value.filter(s => s.status === 'degraded').length,
)
const totalCount = computed(() => deployed.value.length)

const isUnified = computed(() => status.value?.gpu?.memoryType === 'unified')
const memUsed = computed(() =>
  isUnified.value ? (status.value?.ram?.used_gb ?? 0) : (status.value?.gpu?.vramUsed ?? 0),
)
const memTotal = computed(() =>
  isUnified.value ? (status.value?.ram?.total_gb ?? 0) : (status.value?.gpu?.vramTotal ?? 0),
)
const memPct = computed(() => {
  if (isUnified.value) return status.value?.ram?.percent ?? 0
  const total = status.value?.gpu?.vramTotal ?? 0
  if (total <= 0) return 0
  return ((status.value?.gpu?.vramUsed ?? 0) / total) * 100
})
const memLabel = computed(() => isUnified.value ? 'Memory' : 'VRAM')
const memColor = computed(() => {
  if (memPct.value > 90) return 'error'
  if (memPct.value > 75) return 'warning'
  return 'primary'
})

const footerStatusColor = computed(() => {
  if (degradedCount.value > 0) return 'text-warning'
  if (onlineCount.value === totalCount.value && totalCount.value > 0) return 'text-success'
  if (totalCount.value > 0) return 'text-warning'
  return 'text-muted'
})

const version = computed(() => status.value?.version ?? '...')
const tier = computed(() => status.value?.tier ?? 'Minimal')
</script>

<template>
  <aside
    class="flex h-screen flex-col border-r border-default bg-elevated transition-[width] duration-200"
    :class="sidebarCollapsed ? 'w-20' : 'w-64'"
  >
    <!-- Logo / Header -->
    <div class="border-b border-default px-4 pb-5 pt-6">
      <template v-if="sidebarCollapsed">
        <div class="flex flex-col items-center">
          <div class="flex size-11 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-lg font-black tracking-tight text-primary">
            DS
          </div>
          <p class="mt-2 font-mono text-[8px] uppercase tracking-widest text-muted">
            v{{ version }}
          </p>
        </div>
      </template>
      <template v-else>
        <pre
          aria-hidden="true"
          class="select-none whitespace-pre font-mono text-[7.5px] leading-[8px] text-primary"
        >    ____
   / __ \ _____ ___   ____ _ ____ ___
  / / / // ___// _ \ / __ `// __ `__ \
 / /_/ // /   /  __// /_/ // / / / / /
/_____//_/    \___/ \__,_//_/ /_/ /_/
    _____
   / ___/ ___   _____ _   __ ___   _____
   \__ \ / _ \ / ___/| | / // _ \ / ___/
  ___/ //  __// /    | |/ //  __// /
 /____/ \___//_/     |___/ \___//_/</pre>
        <p class="mt-2.5 font-mono text-[8px] uppercase tracking-[0.28em] text-primary">
          LOCAL AI // SOVEREIGN INTELLIGENCE
        </p>
        <p class="mt-1 text-[10px] text-muted">
          {{ tier }} · v{{ version }}
        </p>
      </template>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 overflow-y-auto overflow-x-hidden p-3">
      <ul class="space-y-1">
        <li v-for="item in navItems" :key="item.to">
          <NuxtLink
            :to="item.to"
            :title="sidebarCollapsed ? item.label : undefined"
            class="group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors"
            :class="[
              sidebarCollapsed ? 'justify-center' : '',
              'text-muted hover:bg-default/40 hover:text-default',
            ]"
            active-class="bg-primary/15 text-primary hover:bg-primary/15 hover:text-primary"
          >
            <UIcon :name="item.icon" class="size-5 shrink-0" />
            <span v-if="!sidebarCollapsed" class="truncate">{{ item.label }}</span>
          </NuxtLink>
        </li>
      </ul>

      <!-- Quick Links -->
      <div v-if="!sidebarCollapsed && links.length > 0" class="mt-5 border-t border-default pt-4">
        <div class="mb-2 flex items-center justify-between px-3">
          <p class="text-[10px] font-semibold uppercase tracking-[0.24em] text-primary">
            Quick Links
          </p>
          <button
            type="button"
            class="font-mono text-[9px] uppercase tracking-widest text-muted transition-colors hover:text-default"
            @click="showAllLinks = !showAllLinks"
          >
            {{ showAllLinks ? 'Show open' : 'View all' }}
          </button>
        </div>
        <ul class="space-y-0.5">
          <li v-for="link in externalShown" :key="link.key">
            <a
              :href="link.healthy ? link.url : undefined"
              :target="link.healthy ? '_blank' : undefined"
              :rel="link.healthy ? 'noopener noreferrer' : undefined"
              class="flex items-start gap-2.5 rounded-lg px-3 py-1.5 transition-colors"
              :class="link.healthy
                ? 'text-default hover:bg-default/40'
                : 'cursor-not-allowed text-muted/40'"
              @click="link.healthy ? null : $event.preventDefault()"
            >
              <UIcon :name="link.icon" class="mt-0.5 size-4 shrink-0" :class="link.healthy ? 'text-primary' : 'text-muted/50'" />
              <span class="text-xs leading-4">{{ link.label }}</span>
              <span
                class="ml-auto font-mono text-[9px] uppercase tracking-widest"
                :class="link.healthy ? 'text-primary' : 'text-muted/50'"
              >{{ link.healthy ? 'OPEN' : '—' }}</span>
            </a>
          </li>
        </ul>
      </div>
    </nav>

    <!-- Toggle button -->
    <div class="mx-3 mb-2 flex" :class="sidebarCollapsed ? 'justify-center' : 'justify-end'">
      <UButton
        :icon="sidebarCollapsed ? 'i-lucide-chevron-right' : 'i-lucide-chevron-left'"
        size="xs"
        color="neutral"
        variant="ghost"
        :aria-label="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="ui.toggleSidebar"
      />
    </div>

    <!-- Status footer -->
    <div class="border-t border-default p-4">
      <div v-if="!sidebarCollapsed" class="mb-2 flex items-center justify-between text-sm">
        <span class="text-muted">Services</span>
        <span :class="footerStatusColor">
          {{ degradedCount > 0
            ? `Online: ${onlineCount}/${totalCount} · ${degradedCount} degraded`
            : `Online: ${onlineCount}/${totalCount}` }}
        </span>
      </div>
      <div v-if="status?.gpu || (isUnified && status?.ram)">
        <div v-if="!sidebarCollapsed" class="mb-1 flex items-center justify-between text-xs text-muted">
          <span>{{ memLabel }}</span>
          <span class="font-mono">{{ memUsed.toFixed(1) }}/{{ memTotal.toFixed(0) }} GB</span>
        </div>
        <UProgress
          :model-value="Math.min(memPct, 100)"
          :max="100"
          size="sm"
          :color="memColor"
          :title="sidebarCollapsed ? `${memLabel}: ${memUsed.toFixed(1)}/${memTotal.toFixed(0)} GB` : undefined"
        />
      </div>
    </div>
  </aside>
</template>

