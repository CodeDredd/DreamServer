<!--
  Finance Guru (Phase 4 Welle C.1a). Pendant zu
  dashboard/src/pages/FinanceGuru.jsx — Tab-Wrapper mit zwei
  Tabs (Strategies, Lotto). Lotto folgt in Welle C.1b.

  Tab-State wird wie im Original via window.location.hash persistiert
  (`#lotto`), damit Bookmarks/Refresh den Tab erhalten.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import StrategiesTab from '~/components/finance-guru/StrategiesTab.vue'

definePageMeta({ layout: 'default' })

type TabId = 'strategies' | 'lotto'

const tab = ref<TabId>('strategies')

onMounted(() => {
  const fromHash = (window.location.hash || '').replace('#', '').trim()
  if (fromHash === 'lotto') tab.value = 'lotto'
})

watch(tab, (v) => {
  if (typeof window === 'undefined') return
  if (v === 'strategies') {
    if (window.location.hash) {
      history.replaceState(null, '', window.location.pathname + window.location.search)
    }
  }
  else {
    window.location.hash = v
  }
})

const tabs = computed(() => [
  { label: 'Paper-Trade Strategien', value: 'strategies' as TabId, icon: 'i-lucide-line-chart' },
  { label: 'Lotto Oracle', value: 'lotto' as TabId, icon: 'i-lucide-ticket' },
])
</script>

<template>
  <UDashboardPanel id="finance-guru">
    <template #header>
      <UDashboardNavbar
        title="Finance Guru"
        description="Paper-Trade Strategien & Lotto Oracle"
        icon="i-lucide-trending-up"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <UTabs v-model="tab" :items="tabs" :ui="{ list: 'mb-4' }">
        <template #content="{ item }">
          <StrategiesTab v-if="item.value === 'strategies'" />
          <div
            v-else
            class="rounded-xl border border-default bg-elevated p-12 text-center text-muted"
          >
            <UIcon name="i-lucide-ticket" class="mx-auto mb-3 size-10 text-primary" />
            <p class="text-lg font-medium text-default">
              Lotto Oracle
            </p>
            <p class="mt-2 text-sm">
              Wird in Welle C.1b nachgereicht.
            </p>
          </div>
        </template>
      </UTabs>
    </template>
  </UDashboardPanel>
</template>
