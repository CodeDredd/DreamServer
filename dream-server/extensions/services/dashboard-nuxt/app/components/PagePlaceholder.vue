<!--
  Placeholder fuer Phase-4-Stub-Pages. Jede Page setzt nur Title + Icon
  + Phase-Welle, der visuelle Aufbau ist hier zentral.
-->
<script setup lang="ts">
const props = defineProps<{
  title: string
  icon: string
  phase?: string
  description?: string
}>()
</script>

<template>
  <div class="mx-auto max-w-4xl p-6 md:p-10">
    <div class="mb-6 flex items-center gap-4">
      <div class="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <UIcon :name="icon" class="size-7" />
      </div>
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-default">
          {{ title }}
        </h1>
        <p class="text-sm text-muted">
          {{ description ?? 'Wird in Phase 4 der Nuxt-Migration implementiert.' }}
        </p>
      </div>
    </div>

    <UCard>
      <template #header>
        <div class="flex items-center justify-between">
          <h2 class="text-base font-semibold text-default">
            Status: in Migration
          </h2>
          <UBadge color="warning" variant="subtle" size="sm">
            {{ phase ?? 'Phase 4' }}
          </UBadge>
        </div>
      </template>
      <p class="text-sm text-muted">
        Diese Seite ist ein Phase-3-Stub. Die React-Variante laeuft
        weiter auf <code>:3001</code> und liefert die produktive
        Funktionalitaet, bis die jeweilige Phase-4-Welle des
        Migrationsplans erledigt ist.
      </p>
      <template #footer>
        <div class="flex items-center justify-between text-xs text-muted">
          <span>
            Plan: <code>dream-server/docs/DASHBOARD-NUXT-MIGRATION.md</code>
          </span>
          <NuxtLink to="/" class="text-primary hover:underline">
            Zurueck zum Dashboard
          </NuxtLink>
        </div>
      </template>
    </UCard>
  </div>
</template>

