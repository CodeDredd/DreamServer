<!--
  Hauptnavigation der Sidebar. Kombiniert die statische Routen-Registry
  (useDashboardRoutes) mit den entdeckten externen Service-Links
  (useExternalLinks). Beide sind reaktiv: predikat-gefiltert ueber dem
  Service-Inventar im Pinia-ORM-Store.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { NavigationMenuItem } from '@nuxt/ui'
import { useDashboardRoutes } from '~/composables/useDashboardRoutes'
import { useExternalLinks } from '~/composables/useExternalLinks'

defineProps<{
  collapsed?: boolean
}>()

const { visibleSidebar } = useDashboardRoutes()
const { visibleLinks } = useExternalLinks()

const navItems = computed<NavigationMenuItem[]>(() =>
  visibleSidebar.value.map(r => ({
    label: r.label,
    icon: r.icon,
    to: r.to,
  })),
)

const externalItems = computed<NavigationMenuItem[]>(() =>
  visibleLinks.value.map(l => ({
    label: l.label,
    icon: l.icon,
    to: l.url,
    target: '_blank',
    badge: { color: 'success', variant: 'subtle', label: 'live' },
  })),
)
</script>

<template>
  <UNavigationMenu
    :collapsed="collapsed"
    :items="navItems"
    orientation="vertical"
    tooltip
    popover
  />

  <div v-if="externalItems.length" class="mt-4">
    <p
      v-if="!collapsed"
      class="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted"
    >
      Services
    </p>
    <UNavigationMenu
      :collapsed="collapsed"
      :items="externalItems"
      orientation="vertical"
      tooltip
      popover
    />
  </div>
</template>

