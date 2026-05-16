<!--
  Finance Guru — Trading-Sub-Route (Phase A).
  Rendert ausschliesslich den Strategies-Tab. Pendant zu der vorigen
  Tab-Variante in pages/finance-guru.vue (UTabs entfernt — Auswahl
  passiert ueber die Sidebar-UTree).
-->
<script setup lang="ts">
import StrategiesTab from '~/components/finance-guru/StrategiesTab.vue'

definePageMeta({ layout: 'default' })
</script>

<template>
  <UDashboardPanel id="finance-guru-trading">
    <template #header>
      <UDashboardNavbar
        title="Finance Guru — Trading"
        description="Paper-Trade Strategien"
        icon="i-lucide-line-chart"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <StrategiesTab />
    </template>
  </UDashboardPanel>
</template>

