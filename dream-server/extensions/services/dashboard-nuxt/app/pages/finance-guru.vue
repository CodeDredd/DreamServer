<!--
  Finance Guru — Default-Redirect (Phase A).
  Die alte Tab-basierte Seite wurde in zwei Sub-Routen aufgeteilt:
    /finance-guru/trading  (Strategies)
    /finance-guru/lotto    (Lotto Orakel)
  Diese Index-Page entscheidet anhand des Service-Inventars, wohin
  navigiert wird. Erhalt der alten URLs:
    /finance-guru          → /finance-guru/trading bevorzugt,
                             sonst /finance-guru/lotto.
    /finance-guru#lotto    → /finance-guru/lotto   (Bookmark-Migration).
-->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '~/stores/system'

definePageMeta({ layout: 'default' })

const router = useRouter()
const system = useSystemStore()

onMounted(async () => {
  // Warten, bis das Service-Inventory einmal geladen wurde — sonst
  // landet der erste Aufruf immer auf der Trading-Page, auch wenn
  // nur lotto-oracle aktiv ist.
  if (!system.serviceIds.length) {
    try { await system.fetchStatus() } catch { /* ignore */ }
  }

  const wantsLotto = (typeof window !== 'undefined'
    && (window.location.hash || '').replace('#', '').trim() === 'lotto')

  const hasFinance = system.hasService('finance-guru') || system.hasService('finance guru')
  const hasLotto   = system.hasService('lotto-oracle') || system.hasService('lotto oracle')

  let target = '/finance-guru/trading'
  if (wantsLotto && hasLotto) target = '/finance-guru/lotto'
  else if (!hasFinance && hasLotto) target = '/finance-guru/lotto'

  void router.replace(target)
})
</script>

<template>
  <UDashboardPanel id="finance-guru-redirect">
    <template #body>
      <div class="flex h-full items-center justify-center p-8 text-sm text-muted">
        Lade Finance Guru …
      </div>
    </template>
  </UDashboardPanel>
</template>
