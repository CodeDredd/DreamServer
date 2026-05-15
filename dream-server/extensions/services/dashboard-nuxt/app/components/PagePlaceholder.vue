<!--
  Placeholder fuer Phase-4-Stub-Pages. Eingebettet in
  UDashboardPanel + UDashboardNavbar (Nuxt UI v4-Pattern), damit auf
  Mobile der Sidebar-Toggle ueber die Navbar verfuegbar ist und alle
  Stub-Pages konsistent in den Dashboard-Shell passen.
-->
<script setup lang="ts">
defineProps<{
  title: string
  icon: string
  phase?: string
  description?: string
}>()
</script>

<template>
  <UDashboardPanel id="page-placeholder">
    <template #header>
      <UDashboardNavbar :title="title" :icon="icon">
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UBadge color="warning" variant="subtle" size="sm">
            {{ phase ?? 'Phase 4' }}
          </UBadge>
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <UPageCard
        :title="title"
        :description="description ?? 'Wird in Phase 4 der Nuxt-Migration implementiert.'"
        :icon="icon"
        variant="subtle"
      >
        <p class="text-sm text-muted">
          Diese Seite ist ein Phase-3-Stub. Die React-Variante laeuft
          weiter auf <code>:3001</code> und liefert die produktive
          Funktionalitaet, bis die jeweilige Phase-4-Welle des
          Migrationsplans erledigt ist.
        </p>

        <template #footer>
          <div class="flex w-full items-center justify-between text-xs text-muted">
            <span>
              Plan: <code>dream-server/docs/DASHBOARD-NUXT-MIGRATION.md</code>
            </span>
            <UButton
              to="/"
              icon="i-lucide-arrow-left"
              color="neutral"
              variant="ghost"
              size="xs"
              label="Zurueck zum Dashboard"
            />
          </div>
        </template>
      </UPageCard>
    </template>
  </UDashboardPanel>
</template>

