<!--
  Finance Guru (Phase 4 Welle C.1a + C.1b). Pendant zu
  dashboard/src/pages/FinanceGuru.jsx — Tab-Wrapper mit zwei
  Tabs (Strategies, Lotto).

  Tab-State wird wie im Original via window.location.hash persistiert
  (`#lotto`), damit Bookmarks/Refresh den Tab erhalten.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import StrategiesTab from '~/components/finance-guru/StrategiesTab.vue'
import LottoTab from '~/components/finance-guru/LottoTab.vue'

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
          <LottoTab v-else />
        </template>
      </UTabs>
    </template>
  </UDashboardPanel>
</template>
