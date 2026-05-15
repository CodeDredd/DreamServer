<!--
  Default-Layout fuer alle authenticated Dashboard-Pages.
  Nuxt UI v4 Dashboard-Pattern: UDashboardGroup als Container,
  UDashboardSidebar mit header/default/footer-Slots, Page-Slot rechts.

  Polling-Hooks (useSystemStatus + useVersion) werden hier einmalig
  aktiviert — die internen `started`-Locks der Composables sorgen
  dafuer, dass das auch bei Hot-Reload nur einmal passiert.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'
import { useSystemStatus } from '~/composables/useSystemStatus'
import { useVersion } from '~/composables/useVersion'
import { useDashboardRoutes } from '~/composables/useDashboardRoutes'

// Polling aktivieren (Polling-Lock im Composable verhindert Mehrfach-
// Start). Rueckgabewerte hier nicht gebraucht — Komponenten greifen
// ueber den Store zu.
useSystemStatus()
useVersion()

const open = ref(false)

const store = useSystemStore()
const { status } = storeToRefs(store)
const bootstrap = computed(() => status.value?.bootstrap ?? null)
const showBootstrap = computed(() => Boolean(bootstrap.value?.active))

// Spotlight-Search ueber alle Sidebar-Routen.
const { visibleSidebar } = useDashboardRoutes()
const searchGroups = computed(() => [{
  id: 'pages',
  label: 'Seiten',
  items: visibleSidebar.value.map(r => ({
    label: r.label,
    icon: r.icon,
    to: r.to,
  })),
}])
</script>

<template>
  <UDashboardGroup unit="rem">
    <UDashboardSidebar
      id="dream-default"
      v-model:open="open"
      collapsible
      resizable
      class="bg-elevated/40"
      :ui="{ footer: 'lg:border-t lg:border-default' }"
    >
      <template #header="{ collapsed }">
        <AppLogo :collapsed="collapsed" />
      </template>

      <template #default="{ collapsed }">
        <UDashboardSearchButton
          :collapsed="collapsed"
          class="bg-transparent ring-default"
        />
        <SidebarMenu :collapsed="collapsed ?? false" />
      </template>

      <template #footer="{ collapsed }">
        <SidebarStatus :collapsed="collapsed ?? false" />
      </template>
    </UDashboardSidebar>

    <UDashboardSearch :groups="searchGroups" />

    <div class="flex min-w-0 flex-1 flex-col">
      <BootstrapBanner v-if="showBootstrap && bootstrap" :bootstrap="bootstrap" />
      <slot />
    </div>
  </UDashboardGroup>
</template>

