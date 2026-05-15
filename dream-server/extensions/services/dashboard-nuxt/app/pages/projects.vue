<!--
  Projects (Phase 4 Welle B.1). Pendant zu
  dashboard/src/pages/Projects.jsx (~340 LoC). Vikunja-Proxy via
  /api/projects/*. Zwei-Pane-Layout: links Projektliste, rechts Tasks
  mit Quick-Add + Done-Toggle.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useProjects } from '~/composables/useProjects'
import type { VikunjaTask } from '~/types/api'

definePageMeta({ layout: 'default' })

const { status, projects, loading, error, fetchTasks, addTask, toggleTaskDone, refresh }
  = useProjects()

const selectedId = ref<string | number | null>(null)
const tasks = ref<VikunjaTask[]>([])
const tasksLoading = ref(false)
const newTaskTitle = ref('')
const adding = ref(false)
const addError = ref<string | null>(null)

const vikunjaReady = computed(() => !!status.value?.available && !!status.value?.configured)

watch(projects, (list) => {
  if (!selectedId.value && list.length) selectedId.value = list[0]!.id
}, { immediate: true })

async function loadTasks(id: string | number | null) {
  if (!id) {
    tasks.value = []
    return
  }
  tasksLoading.value = true
  try {
    tasks.value = await fetchTasks(id)
  }
  finally {
    tasksLoading.value = false
  }
}

watch(selectedId, loadTasks)

async function onAdd() {
  if (!newTaskTitle.value.trim() || !selectedId.value) return
  adding.value = true
  addError.value = null
  try {
    await addTask(selectedId.value, newTaskTitle.value.trim())
    newTaskTitle.value = ''
    await loadTasks(selectedId.value)
  }
  catch (e: unknown) {
    addError.value = (e as Error).message
  }
  finally {
    adding.value = false
  }
}

async function onToggle(t: VikunjaTask) {
  await toggleTaskDone(t)
  if (selectedId.value) await loadTasks(selectedId.value)
}

const statusBanner = computed(() => {
  const s = status.value
  if (!s) return null
  if (s.available && s.configured) {
    return { color: 'success' as const, icon: 'i-lucide-check-circle', title: `Vikunja ready${s.version ? ` (v${s.version})` : ''}` }
  }
  if (!s.configured) {
    return {
      color: 'warning' as const,
      icon: 'i-lucide-alert-triangle',
      title: 'VIKUNJA_API_TOKEN nicht konfiguriert',
      description: 'In Vikunja → Settings → API Tokens einen Token mit write-Scope auf projects+tasks anlegen, in .env als VIKUNJA_API_TOKEN=tk_… eintragen, dann dream restart vikunja dashboard-api.',
    }
  }
  return { color: 'error' as const, icon: 'i-lucide-alert-circle', title: s.message || 'Vikunja unreachable' }
})
</script>

<template>
  <UDashboardPanel id="projects">
    <template #header>
      <UDashboardNavbar
        title="Projects"
        description="Vikunja-Projekte und Tasks via dashboard-api"
        icon="i-lucide-list-checks"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-refresh-cw"
            size="sm"
            :loading="loading"
            @click="refresh"
          />
          <UButton
            v-if="status?.url"
            color="neutral"
            variant="ghost"
            icon="i-lucide-external-link"
            size="sm"
            :to="status.url"
            target="_blank"
            rel="noreferrer"
            label="Open Vikunja"
          />
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <div class="flex h-full flex-col gap-4">
        <UAlert
          v-if="statusBanner"
          :color="statusBanner.color"
          variant="subtle"
          :icon="statusBanner.icon"
          :title="statusBanner.title"
          :description="statusBanner.description"
        />
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-alert-triangle"
          title="Fehler"
          :description="error"
        />

        <div class="grid min-h-0 flex-1 gap-4 md:grid-cols-[18rem_1fr]">
          <!-- Project list -->
          <UCard
            :ui="{ body: 'p-0', header: 'px-4 py-3' }"
          >
            <template #header>
              <p class="text-xs font-semibold uppercase tracking-wider text-muted">
                Projekte
              </p>
            </template>
            <div v-if="loading" class="flex items-center gap-2 p-4 text-sm text-muted">
              <UIcon name="i-lucide-loader-2" class="animate-spin" /> Laden…
            </div>
            <div v-else-if="!projects.length" class="p-4 text-sm text-muted">
              Keine Projekte. In Vikunja anlegen, dann hier aktualisieren.
            </div>
            <ul v-else class="divide-y divide-default">
              <li v-for="p in projects" :key="p.id">
                <button
                  type="button"
                  class="w-full px-4 py-3 text-left transition-colors hover:bg-elevated"
                  :class="selectedId === p.id ? 'bg-elevated' : ''"
                  @click="selectedId = p.id"
                >
                  <div class="truncate text-sm font-medium text-default">
                    {{ p.title || `Project #${p.id}` }}
                  </div>
                  <div v-if="p.description" class="mt-0.5 line-clamp-1 text-xs text-muted">
                    {{ p.description }}
                  </div>
                </button>
              </li>
            </ul>
          </UCard>

          <!-- Task pane -->
          <UCard :ui="{ body: 'p-0' }">
            <template v-if="selectedId">
              <!-- Quick add -->
              <form
                class="flex items-stretch gap-2 border-b border-default p-4"
                @submit.prevent="onAdd"
              >
                <UInput
                  v-model="newTaskTitle"
                  placeholder="Neuer Task…"
                  class="flex-1"
                  :disabled="!vikunjaReady || adding"
                />
                <UButton
                  type="submit"
                  color="primary"
                  icon="i-lucide-plus"
                  size="sm"
                  label="Add"
                  :loading="adding"
                  :disabled="!vikunjaReady || !newTaskTitle.trim()"
                />
              </form>
              <p v-if="addError" class="px-4 pt-2 text-xs text-error">
                {{ addError }}
              </p>

              <div v-if="tasksLoading" class="flex items-center gap-2 p-4 text-sm text-muted">
                <UIcon name="i-lucide-loader-2" class="animate-spin" /> Tasks laden…
              </div>
              <div v-else-if="!tasks.length" class="p-6 text-sm text-muted">
                Keine Tasks. Über das Eingabefeld oben oder via Open Claw anlegen.
              </div>
              <ul v-else>
                <li
                  v-for="t in tasks"
                  :key="t.id"
                  class="flex items-start gap-3 border-b border-default px-4 py-3 last:border-b-0"
                >
                  <UButton
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    square
                    :icon="t.done ? 'i-lucide-check-square' : 'i-lucide-square'"
                    :title="t.done ? 'Als offen markieren' : 'Als erledigt markieren'"
                    @click="onToggle(t)"
                  />
                  <div class="min-w-0 flex-1">
                    <p
                      class="text-sm"
                      :class="t.done ? 'text-muted line-through' : 'text-default'"
                    >
                      {{ t.title }}
                    </p>
                    <p v-if="t.description" class="mt-0.5 line-clamp-2 text-xs text-muted">
                      {{ t.description }}
                    </p>
                  </div>
                </li>
              </ul>
            </template>
            <div v-else class="flex h-full items-center justify-center p-12 text-sm text-muted">
              Projekt links auswählen.
            </div>
          </UCard>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>

