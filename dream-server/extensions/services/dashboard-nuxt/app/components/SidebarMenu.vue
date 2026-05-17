<!--
  Hauptnavigation der Sidebar. Kombiniert die statische Routen-Registry
  (useDashboardRoutes) mit den entdeckten externen Service-Links
  (useExternalLinks). Beide sind reaktiv: predikat-gefiltert ueber dem
  Service-Inventar im Pinia-ORM-Store.

  Phase A: Hauptmenue verwendet UTree, damit Routen mit `children`
  (z.B. Finance Guru -> Trading + Lotto Orakel) als ausklappbarer
  Baum erscheinen. Externe Service-Links bleiben flach (kein
  hierarchischer Bedarf).
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { NavigationMenuItem } from '@nuxt/ui'
import type { DashboardRoute } from '~/composables/useDashboardRoutes'
import { useDashboardRoutes } from '~/composables/useDashboardRoutes'
import { useExternalLinks } from '~/composables/useExternalLinks'
import { useEnrichmentHealth } from '~/composables/useEnrichmentHealth'
import { useRoute, useRouter } from 'vue-router'

defineProps<{
  collapsed?: boolean
}>()

const { visibleSidebar } = useDashboardRoutes()
const { visibleLinks } = useExternalLinks()
const { badge: enrichmentBadge } = useEnrichmentHealth()
const route = useRoute()
const router = useRouter()

// Phase P-5: Route-IDs, denen wir ein dynamisches Badge anhaengen
// koennen. Aktuell nur die Trading-Leaf — sie ist der primaere
// Einstieg in Finance-Guru und damit der natuerliche Ort fuer den
// /enrichment/health-Verdict.
type DynamicBadge = NonNullable<NavigationMenuItem['badge']>
function badgeForRoute(id: string): DynamicBadge | undefined {
  if (id === 'finance-guru.trading') {
    const b = enrichmentBadge.value
    if (!b) return undefined
    return {
      label:   b.label,
      color:   b.color,
      variant: 'subtle',
      title:   b.title,
    } as DynamicBadge
  }
  return undefined
}

// UTree-Item-Shape: { label, icon, value, to?, children?, badge? }.
// `value` ist die Route-ID; sie ist auch der TreeRoot-Selection-Key.
interface TreeItem {
  label: string
  icon: string
  value: string
  to?: string
  children?: TreeItem[]
  badge?: DynamicBadge
}

function toTreeItem(r: DashboardRoute): TreeItem {
  return {
    label: r.label,
    icon: r.icon,
    value: r.id,
    to: r.to,
    children: r.children?.map(toTreeItem),
    badge: badgeForRoute(r.id),
  }
}

const treeItems = computed<TreeItem[]>(() =>
  visibleSidebar.value.map(toTreeItem),
)

// Selektierter Tree-Knoten = aktuelle Route. Container-Knoten ohne
// `to` werden nicht selektiert (nur Leaves matchen).
function findMatchingId(items: TreeItem[], path: string): string | null {
  for (const it of items) {
    if (it.to && (path === it.to || path.startsWith(it.to + '/'))) {
      return it.value
    }
    if (it.children) {
      const k = findMatchingId(it.children, path)
      if (k) return k
    }
  }
  return null
}

const selectedId = computed(() => findMatchingId(treeItems.value, route.path))

// Defaults expanded: jeder Container, der den aktiven Leaf-Pfad
// enthaelt — Sidebar startet aufgeklappt fuer den aktuellen Bereich.
const defaultExpanded = computed(() => {
  const expanded: string[] = []
  function walk(items: TreeItem[]) {
    for (const it of items) {
      if (it.children?.length) {
        if (findMatchingId(it.children, route.path)) {
          expanded.push(it.value)
        }
        walk(it.children)
      }
    }
  }
  walk(treeItems.value)
  return expanded
})

// onSelect-Handler: bei Leaves navigieren. Bei Containern macht UTree
// per Default den Toggle (children aufklappen) — wir blocken nur den
// Navigation-Pfad, wenn es kein `to` gibt.
function onTreeSelect(_evt: Event, item: TreeItem) {
  if (item.to) {
    void router.push(item.to)
  }
}

const externalItems = computed<NavigationMenuItem[]>(() =>
  visibleLinks.value.map(l => ({
    label: l.label,
    icon: l.icon,
    to: l.url,
    target: '_blank',
    badge: { color: 'success', variant: 'subtle', label: 'live' },
  })),
)

// Im Collapsed-Modus (Sidebar-Toggle) hat UTree keine Icons-only-
// Variante. Wir greifen dann auf die alte flache Render-Variante
// zurueck: jeder sichtbare Knoten wird als Icon-Tooltip-Eintrag
// flachgelegt.
function flattenForCollapsed(items: TreeItem[]): NavigationMenuItem[] {
  const out: NavigationMenuItem[] = []
  function walk(list: TreeItem[]) {
    for (const it of list) {
      if (it.to) {
        const entry: NavigationMenuItem = { label: it.label, icon: it.icon, to: it.to }
        if (it.badge) entry.badge = it.badge
        out.push(entry)
      }
      if (it.children) walk(it.children)
    }
  }
  walk(items)
  return out
}

const collapsedItems = computed<NavigationMenuItem[]>(() =>
  flattenForCollapsed(treeItems.value),
)
</script>

<template>
  <!-- Collapsed: flache NavigationMenu (Icons + Tooltip). -->
  <UNavigationMenu
    v-if="collapsed"
    :collapsed="true"
    :items="collapsedItems"
    orientation="vertical"
    tooltip
    popover
  />

  <!-- Expanded: hierarchischer UTree mit Container/Children. -->
  <UTree
    v-else
    :items="treeItems"
    :model-value="selectedId ?? undefined"
    :default-expanded="defaultExpanded"
    size="sm"
    color="primary"
    @select="onTreeSelect"
  >
    <!-- Phase P-5: Badge fuer Finance-Guru-Trading (enrichment health). -->
    <template #item-trailing="{ item }">
      <UBadge
        v-if="(item as TreeItem).badge"
        :color="(item as TreeItem).badge!.color as any"
        :variant="((item as TreeItem).badge!.variant as any) ?? 'subtle'"
        :title="(item as TreeItem).badge!.title as string | undefined"
        size="xs"
      >
        {{ (item as TreeItem).badge!.label }}
      </UBadge>
    </template>
  </UTree>

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

