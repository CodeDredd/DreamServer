<!--
  Repo → Project Map (Phase 4 Welle B.3). Pendant zu
  dashboard/src/pages/RepoProjectMap.jsx (~415 LoC). Mappt GitHub
  owner/repo auf Vikunja-Projekt-IDs für den n8n-Workflow
  "GitHub Issue → Vikunja Task". Nutzt /api/repo-map/* + /api/projects.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useProjects } from '~/composables/useProjects'
import { REPO_RE, useRepoMap } from '~/composables/useRepoMap'

definePageMeta({ layout: 'default' })

const { status: vikunjaStatus, projects, refresh: refreshVikunja } = useProjects()
const { map, loading, error, addMapping, deleteMapping, setDefaultProject, refresh: refreshMap }
  = useRepoMap()

const vikunjaReady = computed(() => !!vikunjaStatus.value?.available && !!vikunjaStatus.value?.configured)

async function refresh() {
  await Promise.all([refreshVikunja(), refreshMap()])
}

// --- Add mapping form ----------------------------------------------------
const newRepo = ref('')
const newProjectId = ref<number | string | null>(null)
const adding = ref(false)
const addError = ref<string | null>(null)

const repoValid = computed(() => REPO_RE.test(newRepo.value.trim()))
const existingRepos = computed(
  () => map.value.mappings.map(m => m.repo.toLowerCase()),
)
const isDuplicate = computed(
  () => existingRepos.value.includes(newRepo.value.trim().toLowerCase()),
)
const canSubmit = computed(
  () => repoValid.value && !isDuplicate.value && newProjectId.value !== null && !adding.value,
)

async function onAdd() {
  if (!canSubmit.value || newProjectId.value === null) return
  adding.value = true
  addError.value = null
  try {
    await addMapping(newRepo.value.trim(), newProjectId.value)
    newRepo.value = ''
    newProjectId.value = null
  }
  catch (e: unknown) {
    addError.value = (e as Error).message
  }
  finally {
    adding.value = false
  }
}

async function onDelete(repo: string) {
  if (!confirm(`Mapping für ${repo} löschen?`)) return
  try {
    await deleteMapping(repo)
  }
  catch (e: unknown) {
    addError.value = (e as Error).message
  }
}

// --- Default project draft ----------------------------------------------
const draftDefault = ref<number | string | null>(null)
const savingDefault = ref(false)
const savedAt = ref<number | null>(null)
const defaultError = ref<string | null>(null)

watch(() => map.value.default_project_id, (v) => { draftDefault.value = v }, { immediate: true })
const defaultDirty = computed(() => draftDefault.value !== map.value.default_project_id)

async function saveDefault() {
  savingDefault.value = true
  defaultError.value = null
  try {
    await setDefaultProject(draftDefault.value)
    savedAt.value = Date.now()
  }
  catch (e: unknown) {
    defaultError.value = (e as Error).message
  }
  finally {
    savingDefault.value = false
  }
}

// Project-Optionen für USelect
const projectOptions = computed(() => [
  { label: '— select project —', value: null },
  ...projects.value.map(p => ({
    label: `${p.title || `Project #${p.id}`} (#${p.id})`,
    value: typeof p.id === 'string' ? Number(p.id) : p.id,
  })),
])

function projectTitleFor(id: number | string): string | null {
  const p = projects.value.find(x => Number(x.id) === Number(id))
  return p?.title ?? null
}
</script>

<template>
  <UDashboardPanel id="repo-map">
    <template #header>
      <UDashboardNavbar
        title="Repo → Project Map"
        description="GitHub-Repos auf Vikunja-Projekte für den n8n-Issue-Workflow mappen"
        icon="i-lucide-git-branch"
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
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <div class="space-y-6">
        <!-- Vikunja status banners -->
        <UAlert
          v-if="vikunjaStatus && !vikunjaReady"
          color="warning"
          variant="subtle"
          icon="i-lucide-alert-triangle"
          title="Vikunja ist nicht bereit"
          :description="vikunjaStatus.message || 'Vikunja muss erreichbar sein, damit wir Projekte zum Mappen anzeigen können.'"
        />
        <UAlert
          v-if="vikunjaReady"
          color="success"
          variant="subtle"
          icon="i-lucide-check-circle"
          :title="`Vikunja ready — ${projects.length} Projekt${projects.length === 1 ? '' : 'e'} verfügbar.`"
        />
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-alert-circle"
          title="Fehler"
          :description="error"
        />

        <!-- Default project card -->
        <UCard>
          <div class="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h3 class="text-sm font-semibold text-default">
                Default project (fallback)
              </h3>
              <p class="mt-1 text-xs text-muted">
                Wird vom n8n-Workflow benutzt, wenn ein GitHub-Repo kein
                explizites Mapping hat.
              </p>
            </div>
            <div class="flex items-center gap-2">
              <USelect
                v-model="draftDefault"
                :items="projectOptions"
                :disabled="!vikunjaReady || savingDefault"
                class="min-w-56"
              />
              <UButton
                color="primary"
                size="sm"
                icon="i-lucide-save"
                label="Save"
                :loading="savingDefault"
                :disabled="!defaultDirty || !vikunjaReady"
                @click="saveDefault"
              />
            </div>
          </div>
          <p v-if="defaultError" class="mt-2 text-xs text-error">
            {{ defaultError }}
          </p>
          <p v-else-if="savedAt" class="mt-2 text-xs text-success">
            Gespeichert.
          </p>
        </UCard>

        <!-- Mappings table -->
        <UCard :ui="{ body: 'p-0' }">
          <template #header>
            <div class="flex items-center justify-between">
              <div>
                <h2 class="text-sm font-semibold text-default">
                  Repository mappings
                </h2>
                <p class="mt-0.5 text-xs text-muted">
                  {{ map.mappings.length }} mapping{{ map.mappings.length === 1 ? '' : 's' }} konfiguriert.
                </p>
              </div>
            </div>
          </template>

          <div v-if="loading" class="flex items-center gap-2 p-6 text-sm text-muted">
            <UIcon name="i-lucide-loader-2" class="animate-spin" /> Laden…
          </div>
          <div v-else-if="!map.mappings.length" class="p-6 text-sm text-muted">
            Noch keine Mappings. Issues von ungemappten Repos landen im
            Default-Projekt.
          </div>
          <table v-else class="w-full">
            <thead>
              <tr class="border-b border-default bg-elevated/40">
                <th class="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted">
                  Repository
                </th>
                <th class="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted">
                  Vikunja project
                </th>
                <th class="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted">
                  Updated
                </th>
                <th class="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="entry in map.mappings"
                :key="entry.repo"
                class="border-b border-default last:border-b-0"
              >
                <td class="px-4 py-3 font-mono text-sm text-default">
                  {{ entry.repo }}
                </td>
                <td class="px-4 py-3 text-sm text-default">
                  <span v-if="projectTitleFor(entry.project_id)">
                    {{ projectTitleFor(entry.project_id) }}
                    <span class="ml-1 text-muted">(#{{ entry.project_id }})</span>
                  </span>
                  <span v-else class="text-warning">
                    Project #{{ entry.project_id }} (not found)
                  </span>
                </td>
                <td class="px-4 py-3 text-xs text-muted">
                  {{ entry.updated_at ? new Date(entry.updated_at).toLocaleString() : '—' }}
                </td>
                <td class="px-4 py-3 text-right">
                  <UButton
                    color="error"
                    variant="ghost"
                    icon="i-lucide-trash-2"
                    size="xs"
                    square
                    title="Mapping löschen"
                    @click="onDelete(entry.repo)"
                  />
                </td>
              </tr>
            </tbody>
          </table>

          <!-- Add mapping form -->
          <form
            class="flex flex-wrap items-start gap-2 border-t border-default bg-elevated/30 p-4"
            @submit.prevent="onAdd"
          >
            <div class="min-w-[16rem] flex-1">
              <UInput
                v-model="newRepo"
                placeholder="owner/repo (z. B. CodeDredd/DreamServer)"
                class="font-mono"
                :disabled="!vikunjaReady || adding"
              />
              <p v-if="newRepo && !repoValid" class="mt-1 text-xs text-error">
                Muss wie „owner/name" aussehen.
              </p>
              <p v-else-if="newRepo && repoValid && isDuplicate" class="mt-1 text-xs text-warning">
                Mapping existiert bereits — erst löschen, dann neu anlegen.
              </p>
            </div>
            <USelect
              v-model="newProjectId"
              :items="projectOptions"
              :disabled="!vikunjaReady || adding"
              class="min-w-56"
            />
            <UButton
              type="submit"
              color="primary"
              icon="i-lucide-plus"
              size="sm"
              label="Add mapping"
              :loading="adding"
              :disabled="!canSubmit"
            />
            <p v-if="addError" class="mt-2 w-full text-xs text-error">
              {{ addError }}
            </p>
          </form>
        </UCard>

        <!-- Hint -->
        <p class="text-xs leading-relaxed text-muted">
          Der n8n-Workflow <code class="text-default">GitHub Issue → Vikunja Task</code>
          ruft <code class="text-default">GET /api/repo-map/lookup?repo=&lt;owner/name&gt;</code>
          bei jedem GitHub-Webhook. Sicherstellen, dass der n8n-Container
          <code class="text-default">DASHBOARD_API_KEY</code> + <code class="text-default">DASHBOARD_API_URL</code>
          in der Env hat.
        </p>
      </div>
    </template>
  </UDashboardPanel>
</template>

