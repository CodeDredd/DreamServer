<!--
  Finance Guru — Lotto-Sub-Route (Phase A).
-->
<script setup lang="ts">
import LottoTab from '~/components/finance-guru/LottoTab.vue'

definePageMeta({ layout: 'default' })
</script>

<template>
  <UDashboardPanel id="finance-guru-lotto">
    <template #header>
      <UDashboardNavbar
        title="Finance Guru — Lotto Orakel"
        description="KI-gestuetzte Tipp-Generierung fuer DE-Lotterien"
        icon="i-lucide-ticket"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <LottoTab />
    </template>
  </UDashboardPanel>
</template>

