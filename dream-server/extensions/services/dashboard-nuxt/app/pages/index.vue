<script setup lang="ts">
// Phase-1-Smoke-Page. Phase 4 (Welle A) ersetzt das durch das echte
// Dashboard (KpiStrip + ServicesGrid + RecentActivity).

const config = useRuntimeConfig()

const { data: health } = await useFetch('/api/health', {
  // Polling kommt erst mit useSystemStatus() in Phase 2.
  default: () => ({ status: 'unknown', timestamp: null as string | null }),
})
</script>

<template>
  <main class="mx-auto max-w-3xl space-y-6 p-8">
    <header class="space-y-1">
      <p class="text-xs uppercase tracking-widest text-primary">
        {{ config.public.appName }} · v{{ config.public.appVersion }}
      </p>
      <h1 class="text-3xl font-semibold">
        Dashboard NG
      </h1>
      <p class="text-sm text-muted">
        Phase 1 — Bootstrap. Migrationsplan:
        <code class="text-xs">dream-server/docs/DASHBOARD-NUXT-MIGRATION.md</code>
      </p>
    </header>

    <UCard>
      <template #header>
        <div class="flex items-center justify-between">
          <h2 class="text-base font-medium">
            Healthcheck
          </h2>
          <UBadge
            :color="health?.status === 'ok' ? 'success' : 'neutral'"
            variant="subtle"
            size="sm"
          >
            {{ health?.status ?? 'unknown' }}
          </UBadge>
        </div>
      </template>

      <pre class="overflow-x-auto rounded-md bg-muted p-3 text-xs">{{ health }}</pre>
    </UCard>

    <UCard>
      <template #header>
        <h2 class="text-base font-medium">
          Roadmap
        </h2>
      </template>

      <ol class="list-decimal space-y-1 pl-5 text-sm text-muted">
        <li>Phase 1 — Bootstrap (✅ this build)</li>
        <li>Phase 2 — Datenschicht (Composables, Pinia-Stores, Pinia-ORM-Modelle, Nitro-API-Proxy)</li>
        <li>Phase 3 — App-Shell + Sidebar (UDashboardGroup, SplashScreen)</li>
        <li>Phase 4 — Pages-Migration in 4 Wellen</li>
        <li>Phase 5 — PWA, Theming, i18n</li>
        <li>Phase 6 — Tests (Unit + Component + E2E)</li>
        <li>Phase 7 — Cutover (14 Tage Soak → Port-Swap)</li>
      </ol>
    </UCard>
  </main>
</template>

