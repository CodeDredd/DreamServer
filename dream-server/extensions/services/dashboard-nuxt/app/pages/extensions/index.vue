<!--
  Extensions / Add-on Service Library (Phase 4 Welle B.5).
  Pendant zu dashboard/src/pages/Extensions.jsx (~1255 LoC) + den drei
  DependencyBadges-Komponenten. Funktional 1:1:
    * Catalog browse mit Status- + Category-Filter + Live-Suche
    * Summary-Strip mit Per-Status-Counts
    * Install/Enable/Disable/Uninstall/Purge mit Confirm-Modal
    * Dependency-Auto-Enable-Dialog (HTTP 400 + missing_dependencies)
    * Detail-Modal (Description / Info-Grid / Deps / Env / Features /
      CLI-Commands)
    * Logs-Modal (POST /api/extensions/{id}/logs alle 2 s, sticky bottom-
      scroll, Disconnect-Banner nach 3 Failures)
  Templates/Quick-Start sind in dieser Welle bewusst raus (separate
  Page in einer späteren Welle).
-->
<script setup lang="ts">
import { computed, defineComponent, h, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  HEADLESS_EXTENSIONS,
  STATUS_DESCRIPTIONS,
  STATUS_FILTERS,
  STATUS_LABELS,
  extensionIcon,
  statusBadge,
  useExtensions,
  type StatusFilter,
} from '~/composables/useExtensions'
import { useApi } from '~/composables/useApi'
import type { ExtensionEntry } from '~/types/api'

definePageMeta({ layout: 'default' })

const {
  extensions,
  summary,
  agentAvailable,
  gpuBackend,
  loading,
  refreshing,
  error,
  mutating,
  pollingLost,
  progressMap,
  refresh,
  mutate,
  fetchLogs,
} = useExtensions()

// ---------- Inline tiny helper components (kept local to avoid a
// dedicated `components/extensions/` directory just for two trivial
// pieces). All three are pure presentational. ---------------------------

const SummaryItem = defineComponent({
  name: 'SummaryItem',
  props: {
    label: { type: String, required: true },
    value: { type: [Number, String], required: true },
    dot: { type: String, required: true },
  },
  setup(props) {
    return () =>
      h('div', { class: 'flex items-center gap-2' }, [
        h('span', { class: `size-1.5 rounded-full ${props.dot}` }),
        h(
          'span',
          { class: 'text-[10px] font-semibold uppercase tracking-[0.13em] text-muted' },
          props.label,
        ),
        h('span', { class: 'font-mono font-medium text-default' }, String(props.value)),
      ])
  },
})

const InfoCell = defineComponent({
  name: 'InfoCell',
  props: { label: { type: String, required: true } },
  setup(props, { slots }) {
    return () =>
      h('div', { class: 'rounded-lg bg-elevated/40 p-3' }, [
        h('span', { class: 'mb-1 block text-xs text-muted' }, props.label),
        h('span', { class: 'text-default' }, slots.default?.()),
      ])
  },
})

const CopyableCommand = defineComponent({
  name: 'CopyableCommand',
  props: { command: { type: String, required: true } },
  setup(props) {
    const copied = ref(false)
    function doCopy() {
      if (typeof navigator !== 'undefined' && navigator.clipboard) {
        void navigator.clipboard.writeText(props.command).then(() => {
          copied.value = true
          setTimeout(() => { copied.value = false }, 1800)
        })
      }
    }
    return () =>
      h(
        'div',
        {
          class:
            'flex items-center justify-between rounded-md bg-elevated px-3 py-1.5 font-mono text-sm text-toned',
        },
        [
          h('span', { class: 'mr-2 truncate' }, props.command),
          h(
            'button',
            {
              class: 'shrink-0 text-muted transition-colors hover:text-default',
              title: copied.value ? 'Copied!' : 'Copy to clipboard',
              onClick: doCopy,
            },
            [h('span', { class: copied.value ? 'i-lucide-check size-3.5 inline-block text-success' : 'i-lucide-copy size-3.5 inline-block' })],
          ),
        ],
      )
  },
})

// ---------- Filter state -----------------------------------------------

const statusFilter = ref<StatusFilter>('all')
const categoryFilter = ref<string>('all')
const search = ref('')

const categoryOptions = computed<string[]>(() => {
  const set = new Set<string>()
  for (const ext of extensions.value) {
    for (const f of ext.features ?? []) {
      if (f.category) set.add(f.category)
    }
  }
  return ['all', ...Array.from(set).sort()]
})

const filtered = computed<ExtensionEntry[]>(() => {
  const q = search.value.trim().toLowerCase()
  return extensions.value.filter((ext) => {
    if (statusFilter.value !== 'all' && ext.status !== statusFilter.value) return false
    if (categoryFilter.value !== 'all'
      && !ext.features?.some(f => f.category === categoryFilter.value)) return false
    if (q
      && !ext.name.toLowerCase().includes(q)
      && !(ext.description?.toLowerCase().includes(q))) return false
    return true
  })
})

// ---------- Modal / dialog state ---------------------------------------

interface ConfirmState {
  action: 'install' | 'enable' | 'disable' | 'uninstall' | 'purge'
  ext: ExtensionEntry
  message: string
}

const confirmState = ref<ConfirmState | null>(null)
const showConfirm = computed({
  get: () => !!confirmState.value,
  set: (v) => { if (!v) confirmState.value = null },
})

interface DepConfirmState {
  ext: ExtensionEntry
  missingDeps: string[]
}
const depConfirm = ref<DepConfirmState | null>(null)
const showDepConfirm = computed({
  get: () => !!depConfirm.value,
  set: (v) => { if (!v) depConfirm.value = null },
})

const detailExtId = ref<string | null>(null)
const detailExt = computed<ExtensionEntry | null>(
  () => extensions.value.find(e => e.id === detailExtId.value) ?? null,
)
const showDetail = computed({
  get: () => !!detailExt.value,
  set: (v) => { if (!v) detailExtId.value = null },
})

const consoleExt = ref<ExtensionEntry | null>(null)
const showConsole = computed({
  get: () => !!consoleExt.value,
  set: (v) => { if (!v) consoleExt.value = null },
})

// ---------- Action helpers ---------------------------------------------

function requestAction(ext: ExtensionEntry, action: ConfirmState['action']) {
  const messages: Record<ConfirmState['action'], string> = {
    install: `Install ${ext.name}? This will download and start the service.`,
    enable: `Enable ${ext.name}? The service will be started.`,
    disable: `Disable ${ext.name}? The service will be stopped.`,
    uninstall: `Remove ${ext.name}? You can reinstall it from the library.`,
    purge: `Permanently delete all data for ${ext.name}? This cannot be undone.`,
  }
  confirmState.value = { action, ext, message: messages[action] }
}

async function runConfirmedAction() {
  const c = confirmState.value
  if (!c) return
  confirmState.value = null
  const out = await mutate(c.ext.id, c.action)
  if (!out.ok && out.missingDependencies && out.ext) {
    depConfirm.value = { ext: out.ext, missingDeps: out.missingDependencies }
  }
}

async function runDepConfirm() {
  const dc = depConfirm.value
  if (!dc) return
  depConfirm.value = null
  await mutate(dc.ext.id, 'enable', { autoEnableDeps: true })
}

// ---------- Card-level computed badges ---------------------------------

function cardCanToggle(ext: ExtensionEntry): boolean {
  if (ext.source !== 'user') return false
  return [
    'enabled',
    'cli_installed',
    'disabled',
    'error',
    'stopped',
    'unhealthy',
  ].includes(ext.status)
}

function cardShowInstall(ext: ExtensionEntry): boolean {
  return ext.status === 'not_installed' && !!ext.installable
}

function cardShowRemove(ext: ExtensionEntry): boolean {
  return ext.source === 'user' && (ext.status === 'disabled' || ext.status === 'error')
}

function externalUrl(ext: ExtensionEntry): string | null {
  const port = ext.external_port_default || ext.port
  if (!port || typeof window === 'undefined') return null
  return `http://${window.location.hostname}:${port}`
}

// ---------- Logs modal (per-instance state) ----------------------------

const logsText = ref('')
const logsLoading = ref(true)
const logsError = ref<string | null>(null)
const logsDisconnected = ref(false)
const logsAtBottom = ref(true)
const logsRef = ref<HTMLElement | null>(null)
let logsTimer: ReturnType<typeof setTimeout> | null = null
let logsActive = false
let logsFails = 0

async function logsTick(serviceId: string) {
  if (!logsActive) return
  try {
    const text = await fetchLogs(serviceId)
    logsText.value = text
    logsError.value = null
    logsDisconnected.value = false
    logsFails = 0
    void nextTick(() => {
      if (logsRef.value && logsAtBottom.value) {
        logsRef.value.scrollTop = logsRef.value.scrollHeight
      }
    })
  }
  catch (err: unknown) {
    logsFails += 1
    logsError.value = (err as Error).message || 'Failed to fetch logs'
    if (logsFails >= 3) logsDisconnected.value = true
  }
  finally {
    logsLoading.value = false
  }
  if (!logsActive) return
  const delay = logsFails > 0
    ? Math.min(2000 * 2 ** (logsFails - 1), 30_000)
    : 2000
  logsTimer = setTimeout(() => logsTick(serviceId), delay)
}

function startLogs(ext: ExtensionEntry) {
  consoleExt.value = ext
  logsText.value = ''
  logsLoading.value = true
  logsError.value = null
  logsDisconnected.value = false
  logsAtBottom.value = true
  logsFails = 0
  logsActive = true
  void logsTick(ext.id)
}

function stopLogs() {
  logsActive = false
  if (logsTimer) {
    clearTimeout(logsTimer)
    logsTimer = null
  }
}

function onLogsScroll() {
  if (!logsRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = logsRef.value
  logsAtBottom.value = scrollHeight - scrollTop - clientHeight < 50
}

function jumpLogsBottom() {
  if (logsRef.value) {
    logsRef.value.scrollTop = logsRef.value.scrollHeight
    logsAtBottom.value = true
  }
}

watch(showConsole, (open) => {
  if (!open) stopLogs()
})

onBeforeUnmount(stopLogs)

// ---------- Detail modal: progress fetch when error/installing ---------

const api = useApi()
const detailProgress = ref<{ status?: string, error?: string, started_at?: string } | null>(null)
watch(detailExt, async (ext) => {
  detailProgress.value = null
  if (!ext) return
  if (ext.status !== 'installing' && ext.status !== 'setting_up' && ext.status !== 'error') return
  try {
    const data = await api.get<{ status: string, error?: string, started_at?: string }>(
      `/api/extensions/${ext.id}/progress`,
    )
    if (data.status !== 'idle') detailProgress.value = data
  }
  catch { /* ignore */ }
})
</script>

<template>
  <UDashboardPanel id="extensions">
    <template #header>
      <UDashboardNavbar
        title="Extensions"
        :description="`${extensions.length} Add-on Services im Katalog`"
        icon="i-lucide-puzzle"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UBadge
            v-if="agentAvailable !== undefined"
            :color="agentAvailable ? 'success' : 'error'"
            variant="subtle"
            size="sm"
            :icon="agentAvailable ? 'i-lucide-radio' : 'i-lucide-radio-tower'"
          >
            {{ agentAvailable ? 'Agent online' : 'Agent offline' }}
          </UBadge>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-refresh-cw"
            size="sm"
            :loading="refreshing"
            @click="refresh"
          >
            Refresh
          </UButton>
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <div class="space-y-4">
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-alert-triangle"
          title="Catalog konnte nicht geladen werden"
          :description="error"
          :actions="[{ label: 'Retry', color: 'error', variant: 'subtle', onClick: () => refresh() }]"
        />

        <UAlert
          v-if="agentAvailable === false"
          color="warning"
          variant="subtle"
          icon="i-lucide-alert-triangle"
          title="Host agent offline"
          description="Install / enable / disable operations are unavailable. Container logs cannot be fetched."
        />

        <UAlert
          v-if="pollingLost"
          color="warning"
          variant="subtle"
          icon="i-lucide-loader-2"
          title="Connection to dashboard lost"
          description="Retrying. Refresh if this persists."
        />

        <!-- Summary strip -->
        <UCard :ui="{ body: 'py-3 px-4' }">
          <div class="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
            <SummaryItem label="Total" :value="summary.total ?? extensions.length" dot="bg-muted" />
            <SummaryItem label="Installed" :value="summary.installed ?? 0" dot="bg-success" />
            <SummaryItem label="Stopped" :value="summary.stopped ?? 0" dot="bg-error" />
            <SummaryItem label="Unhealthy" :value="summary.unhealthy ?? 0" dot="bg-warning" />
            <SummaryItem label="Available" :value="summary.not_installed ?? 0" dot="bg-primary" />
            <SummaryItem label="Installing" :value="summary.installing ?? 0" dot="bg-info" />
            <SummaryItem label="Error" :value="summary.error ?? 0" dot="bg-error" />
            <SummaryItem label="Incompatible" :value="summary.incompatible ?? 0" dot="bg-warning" />
            <UPopover mode="hover" class="ml-auto">
              <UButton
                color="neutral"
                variant="ghost"
                size="xs"
                icon="i-lucide-info"
                square
              />
              <template #content>
                <div class="w-96 p-3 text-xs">
                  <h4 class="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
                    Status Legend
                  </h4>
                  <div class="grid grid-cols-[6.5rem_1fr] items-baseline gap-x-3 gap-y-2">
                    <template v-for="(desc, key) in STATUS_DESCRIPTIONS" :key="key">
                      <UBadge
                        :color="statusBadge(String(key)).color"
                        variant="subtle"
                        size="xs"
                        class="justify-center"
                      >
                        {{ String(key).replace(/_/g, ' ') }}
                      </UBadge>
                      <span class="leading-4 text-toned">{{ desc }}</span>
                    </template>
                  </div>
                </div>
              </template>
            </UPopover>
          </div>
        </UCard>

        <!-- Status filter row -->
        <div class="flex flex-wrap items-center gap-1.5">
          <UButton
            v-for="s in STATUS_FILTERS"
            :key="s"
            :color="statusFilter === s ? 'primary' : 'neutral'"
            :variant="statusFilter === s ? 'soft' : 'ghost'"
            size="xs"
            class="rounded-full"
            @click="statusFilter = s"
          >
            {{ STATUS_LABELS[s] }}
          </UButton>
        </div>

        <!-- Category + search row -->
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div class="flex flex-wrap items-center gap-1.5">
            <UButton
              v-for="cat in categoryOptions"
              :key="cat"
              color="neutral"
              :variant="categoryFilter === cat ? 'soft' : 'ghost'"
              size="xs"
              class="rounded-full"
              @click="categoryFilter = cat"
            >
              {{ cat === 'all' ? 'All Categories' : cat }}
            </UButton>
          </div>
          <UInput
            v-model="search"
            placeholder="Search extensions…"
            icon="i-lucide-search"
            size="sm"
            class="sm:ml-auto sm:w-64"
          />
        </div>

        <!-- Loading skeleton -->
        <div v-if="loading && !extensions.length" class="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          <USkeleton v-for="i in 6" :key="i" class="h-44 w-full rounded-xl" />
        </div>

        <!-- Empty state -->
        <div
          v-else-if="filtered.length === 0"
          class="flex flex-col items-center justify-center rounded-xl border border-dashed border-default py-16 text-muted"
        >
          <UIcon name="i-lucide-package" class="mb-3 size-10 opacity-40" />
          <p class="text-sm font-semibold">
            No extensions match
          </p>
          <p class="mt-1 text-[10px] uppercase tracking-[0.14em] text-muted">
            Try adjusting your search or filters
          </p>
        </div>

        <!-- Card grid -->
        <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          <UCard
            v-for="ext in filtered"
            :key="ext.id"
            :ui="{ body: 'p-0' }"
            class="flex flex-col"
          >
            <!-- Card body -->
            <div class="flex-1 px-4 pb-3 pt-4">
              <div class="mb-2 flex items-start justify-between gap-2">
                <div class="flex items-center gap-2.5">
                  <div class="rounded-lg bg-elevated p-1.5">
                    <UIcon
                      :name="extensionIcon(ext)"
                      :class="[
                        'size-4',
                        ext.status === 'enabled' || ext.status === 'cli_installed'
                          ? 'text-success'
                          : ext.status === 'stopped' || ext.status === 'error'
                            ? 'text-error'
                            : ext.status === 'unhealthy' || ext.status === 'incompatible'
                              ? 'text-warning'
                              : ext.status === 'installing' || ext.status === 'setting_up'
                                ? 'text-info'
                                : 'text-muted',
                      ]"
                    />
                  </div>
                  <div>
                    <h3 class="text-sm font-semibold leading-tight text-default">
                      {{ ext.name }}
                    </h3>
                    <span
                      v-if="ext.features?.[0]?.category"
                      class="text-[9px] uppercase tracking-[0.18em] text-muted"
                    >
                      {{ ext.features[0].category }}
                    </span>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <UBadge
                    v-if="ext.source === 'core'"
                    color="info"
                    variant="subtle"
                    size="xs"
                    title="Built-in service — managed by DreamServer"
                  >
                    core
                  </UBadge>
                  <UBadge
                    v-else
                    :color="statusBadge(ext.status).color"
                    variant="subtle"
                    size="xs"
                    :title="STATUS_DESCRIPTIONS[ext.status]"
                    :class="ext.status === 'error' ? 'cursor-pointer' : ''"
                    @click="ext.status === 'error' ? startLogs(ext) : null"
                  >
                    <UIcon
                      v-if="ext.status === 'installing' || ext.status === 'setting_up'"
                      name="i-lucide-loader-2"
                      class="mr-1 size-2.5 animate-spin"
                    />
                    {{ statusBadge(ext.status).label }}
                  </UBadge>
                  <USwitch
                    v-if="cardCanToggle(ext)"
                    :model-value="ext.status === 'enabled' || ext.status === 'cli_installed'"
                    :loading="mutating === ext.id"
                    :disabled="!!mutating || agentAvailable === false"
                    size="xs"
                    @update:model-value="
                      requestAction(ext, ext.status === 'disabled' ? 'enable' : 'disable')
                    "
                  />
                </div>
              </div>
              <p class="line-clamp-2 text-[11px] leading-relaxed text-toned">
                {{ ext.description || 'No description available.' }}
              </p>
              <div
                v-if="ext.depends_on?.length"
                class="mt-2 flex flex-wrap items-center gap-1.5"
              >
                <span class="text-[10px] text-muted">Requires:</span>
                <UBadge
                  v-for="dep in ext.depends_on"
                  :key="dep"
                  :color="
                    ext.dependency_status?.[dep] === 'enabled' ? 'success'
                    : ext.dependency_status?.[dep] === 'incompatible' ? 'warning'
                      : 'neutral'
                  "
                  variant="subtle"
                  size="xs"
                  :title="`${dep}: ${ext.dependency_status?.[dep] || 'unknown'}`"
                >
                  {{ dep }}
                </UBadge>
              </div>
            </div>

            <!-- Progress / error strip -->
            <div
              v-if="progressMap[ext.id] || ext.status === 'installing' || ext.status === 'setting_up'"
              class="flex items-center gap-2 border-t border-default px-4 py-2 text-[10px] text-info"
            >
              <UIcon name="i-lucide-loader-2" class="size-3 animate-spin" />
              <span>{{
                progressMap[ext.id]?.phase_label
                  || (ext.status === 'setting_up' ? 'Running setup…' : 'Installing…')
              }}</span>
            </div>
            <div
              v-if="ext.status === 'error' && progressMap[ext.id]?.error"
              class="border-t border-default px-4 py-2 text-[10px] leading-relaxed text-error"
            >
              <details>
                <summary class="cursor-pointer">
                  {{ (progressMap[ext.id]?.error || '').split('\n')[0].slice(0, 120) }}
                  <span v-if="(progressMap[ext.id]?.error || '').length > 120">…</span>
                </summary>
                <pre class="mt-2 whitespace-pre-wrap break-words font-mono text-[10px]">{{ progressMap[ext.id]?.error }}</pre>
              </details>
            </div>

            <!-- Card footer -->
            <div class="flex items-center justify-between gap-2 border-t border-default bg-elevated/40 px-4 py-2.5">
              <div class="flex flex-wrap items-center gap-1.5">
                <UButton
                  v-if="cardShowInstall(ext)"
                  color="primary"
                  size="xs"
                  icon="i-lucide-download"
                  :loading="mutating === ext.id"
                  :disabled="!!mutating || agentAvailable === false"
                  @click="requestAction(ext, 'install')"
                >
                  Install
                </UButton>
                <UButton
                  v-if="ext.source === 'user' && ext.status === 'stopped'"
                  color="success"
                  variant="soft"
                  size="xs"
                  :loading="mutating === ext.id"
                  :disabled="!!mutating || agentAvailable === false"
                  @click="requestAction(ext, 'enable')"
                >
                  Start
                </UButton>
                <UButton
                  v-if="ext.source === 'user' && ext.status === 'unhealthy'"
                  color="warning"
                  variant="soft"
                  size="xs"
                  icon="i-lucide-terminal"
                  :disabled="agentAvailable === false"
                  @click="startLogs(ext)"
                >
                  Check Logs
                </UButton>
                <UButton
                  v-if="ext.status === 'error'"
                  color="info"
                  variant="soft"
                  size="xs"
                  icon="i-lucide-refresh-cw"
                  :loading="mutating === ext.id"
                  :disabled="!!mutating || agentAvailable === false"
                  @click="requestAction(ext, 'enable')"
                >
                  Retry
                </UButton>
                <UButton
                  v-if="cardShowRemove(ext)"
                  color="error"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-trash-2"
                  :loading="mutating === ext.id"
                  :disabled="!!mutating || agentAvailable === false"
                  @click="requestAction(ext, 'uninstall')"
                >
                  Remove
                </UButton>
                <UButton
                  v-if="cardShowRemove(ext) && ext.has_data"
                  color="warning"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-database"
                  :loading="mutating === ext.id"
                  :disabled="!!mutating"
                  title="Permanently delete service data"
                  @click="requestAction(ext, 'purge')"
                >
                  Purge Data
                </UButton>
                <span
                  v-if="ext.source === 'user' && (ext.status === 'enabled' || ext.status === 'cli_installed')"
                  class="text-[9px] uppercase tracking-[0.14em] text-muted"
                >
                  Disable to remove
                </span>
                <template
                  v-if="!cardShowInstall(ext) && !cardShowRemove(ext) && !cardCanToggle(ext) && ext.gpu_backends?.length"
                >
                  <span
                    v-if="ext.status === 'incompatible'"
                    class="text-[9px] uppercase tracking-[0.14em] text-muted"
                  >Requires:</span>
                  <UBadge
                    v-for="gpu in ext.gpu_backends.slice(0, 3)"
                    :key="gpu"
                    color="neutral"
                    variant="outline"
                    size="xs"
                    class="font-mono"
                  >
                    {{ gpu }}
                  </UBadge>
                </template>
              </div>
              <div class="flex items-center gap-1">
                <a
                  v-if="ext.status === 'enabled' && externalUrl(ext) && !HEADLESS_EXTENSIONS.has(ext.id)"
                  :href="externalUrl(ext) || '#'"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="flex items-center gap-1 rounded-md px-2 py-1 font-mono text-[10px] text-toned hover:bg-elevated hover:text-default"
                  :title="`Open on port ${ext.external_port_default || ext.port}`"
                  @click.stop
                >
                  <UIcon name="i-lucide-external-link" class="size-3" />
                  :{{ ext.external_port_default || ext.port }}
                </a>
                <span
                  v-else-if="ext.status === 'enabled' && HEADLESS_EXTENSIONS.has(ext.id)"
                  class="px-2 font-mono text-[9px] uppercase tracking-[0.12em] text-muted"
                >
                  API service
                </span>
                <UButton
                  v-if="(ext.source === 'user' || ext.source === 'core') && ext.status !== 'not_installed'"
                  color="neutral"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-terminal"
                  :disabled="agentAvailable === false"
                  :title="agentAvailable === false ? 'Agent offline' : 'View logs'"
                  @click="startLogs(ext)"
                >
                  Logs
                </UButton>
                <UButton
                  color="neutral"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-info"
                  square
                  @click="detailExtId = ext.id"
                />
              </div>
            </div>
          </UCard>
        </div>
      </div>
    </template>

    <!-- ===== Confirm dialog ===== -->
    <UModal v-model:open="showConfirm" :ui="{ width: 'sm:max-w-md' }">
      <template #content>
        <UCard v-if="confirmState">
          <template #header>
            <h3 class="text-base font-semibold capitalize">
              {{ confirmState.action === 'uninstall' ? 'Remove'
                : confirmState.action === 'purge' ? 'Purge Data'
                  : confirmState.action }} Extension
            </h3>
          </template>
          <p class="text-sm leading-relaxed text-toned">
            {{ confirmState.message }}
          </p>
          <UAlert
            v-if="confirmState.action === 'disable' && confirmState.ext.dependents?.length"
            color="warning"
            variant="subtle"
            icon="i-lucide-alert-triangle"
            class="mt-3"
            title="May break dependents"
            :description="`Disabling this may break: ${confirmState.ext.dependents.join(', ')}`"
          />
          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton color="neutral" variant="ghost" @click="confirmState = null">
                Cancel
              </UButton>
              <UButton
                :color="confirmState.action === 'uninstall' || confirmState.action === 'purge' ? 'error' : 'primary'"
                :loading="mutating === confirmState.ext.id"
                @click="runConfirmedAction"
              >
                {{ confirmState.action === 'uninstall' ? 'Remove'
                  : confirmState.action === 'purge' ? 'Purge'
                    : confirmState.action.charAt(0).toUpperCase() + confirmState.action.slice(1) }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>

    <!-- ===== Dependency auto-enable confirm ===== -->
    <UModal v-model:open="showDepConfirm" :ui="{ width: 'sm:max-w-md' }">
      <template #content>
        <UCard v-if="depConfirm">
          <template #header>
            <h3 class="text-base font-semibold">
              Enable Dependencies
            </h3>
          </template>
          <p class="text-sm text-toned">
            Enabling <span class="font-medium text-default">{{ depConfirm.ext.name }}</span> will also enable:
          </p>
          <div class="mt-3 flex flex-wrap gap-2">
            <UBadge
              v-for="dep in depConfirm.missingDeps"
              :key="dep"
              color="primary"
              variant="subtle"
            >
              {{ dep }}
            </UBadge>
          </div>
          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton color="neutral" variant="ghost" @click="depConfirm = null">
                Cancel
              </UButton>
              <UButton color="primary" :loading="mutating === depConfirm.ext.id" @click="runDepConfirm">
                Enable All
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>

    <!-- ===== Detail modal ===== -->
    <UModal v-model:open="showDetail" :ui="{ width: 'sm:max-w-lg' }">
      <template #content>
        <UCard v-if="detailExt" :ui="{ body: 'max-h-[70vh] overflow-y-auto' }">
          <template #header>
            <div class="flex items-center gap-3">
              <UIcon :name="extensionIcon(detailExt)" class="size-6 text-muted" />
              <div class="flex-1">
                <h3 class="text-lg font-semibold">
                  {{ detailExt.name }}
                </h3>
                <UBadge
                  :color="statusBadge(detailExt.status).color"
                  variant="subtle"
                  size="xs"
                  class="mt-0.5"
                >
                  {{ statusBadge(detailExt.status).label }}
                </UBadge>
              </div>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                size="xs"
                square
                @click="detailExtId = null"
              />
            </div>
          </template>
          <div class="space-y-4">
            <p class="text-sm text-toned">
              {{ detailExt.description || 'No description available.' }}
            </p>
            <UAlert
              v-if="detailProgress?.error"
              color="error"
              variant="subtle"
              icon="i-lucide-alert-triangle"
              title="Last installer error"
              :description="detailProgress.error"
            />
            <div class="grid grid-cols-2 gap-3 text-sm">
              <InfoCell label="Port">
                <span class="font-mono">{{ detailExt.external_port_default || detailExt.port || '—' }}</span>
              </InfoCell>
              <InfoCell label="GPU">
                <span>{{ detailExt.gpu_backends?.join(', ') || 'none' }}</span>
                <span
                  v-if="detailExt.status === 'incompatible' && gpuBackend"
                  class="mt-0.5 block text-[10px] text-warning"
                >Your system: {{ gpuBackend }}</span>
              </InfoCell>
              <InfoCell label="Category">
                {{ detailExt.category || '—' }}
              </InfoCell>
              <InfoCell label="Health">
                <span class="font-mono text-xs">{{ detailExt.health_endpoint || '—' }}</span>
              </InfoCell>
            </div>
            <div v-if="detailExt.depends_on?.length">
              <h4 class="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted">
                Dependencies
              </h4>
              <div class="flex flex-wrap gap-1.5">
                <UBadge
                  v-for="dep in detailExt.depends_on"
                  :key="dep"
                  color="neutral"
                  variant="subtle"
                  size="xs"
                >
                  {{ dep }}
                </UBadge>
              </div>
            </div>
            <div v-if="detailExt.env_vars?.length">
              <h4 class="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted">
                Environment Variables
              </h4>
              <div class="overflow-hidden rounded-lg border border-default">
                <table class="w-full text-sm">
                  <thead class="bg-elevated/50">
                    <tr>
                      <th class="px-3 py-2 text-left text-xs font-medium text-muted">
                        Key
                      </th>
                      <th class="px-3 py-2 text-left text-xs font-medium text-muted">
                        Description
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="v in detailExt.env_vars"
                      :key="v.key || v.name"
                      class="border-t border-default"
                    >
                      <td class="px-3 py-2 font-mono text-xs text-primary">
                        {{ v.key || v.name }}
                      </td>
                      <td class="px-3 py-2 text-xs text-toned">
                        {{ v.description || '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-if="detailExt.features?.length">
              <h4 class="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted">
                Features
              </h4>
              <ul class="space-y-1 text-sm">
                <li v-for="f in detailExt.features" :key="f.name" class="flex items-center gap-2">
                  <span class="size-1.5 rounded-full bg-primary" />
                  <span class="text-toned">{{ f.name }}</span>
                  <span v-if="f.category" class="text-xs text-muted">({{ f.category }})</span>
                </li>
              </ul>
            </div>
            <div>
              <h4 class="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted">
                CLI Commands
              </h4>
              <div class="space-y-1.5">
                <CopyableCommand :command="`dream enable ${detailExt.id}`" />
                <CopyableCommand :command="`dream disable ${detailExt.id}`" />
              </div>
            </div>
          </div>
        </UCard>
      </template>
    </UModal>

    <!-- ===== Logs modal ===== -->
    <UModal v-model:open="showConsole" :ui="{ width: 'sm:max-w-3xl' }">
      <template #content>
        <UCard v-if="consoleExt" :ui="{ body: 'p-0', root: 'h-[70vh] flex flex-col' }">
          <template #header>
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <UIcon
                  name="i-lucide-terminal"
                  :class="logsDisconnected ? 'text-error' : 'text-success'"
                />
                <span class="text-sm font-medium">{{ consoleExt.name }}</span>
                <span class="text-xs text-muted">logs</span>
                <span
                  class="size-1.5 rounded-full"
                  :class="logsDisconnected ? 'bg-error' : 'bg-success animate-pulse'"
                  :title="logsDisconnected ? 'Disconnected' : 'Live'"
                />
              </div>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                size="xs"
                square
                @click="consoleExt = null"
              />
            </div>
          </template>
          <div class="relative flex-1 overflow-hidden">
            <div
              ref="logsRef"
              class="absolute inset-0 overflow-y-auto whitespace-pre-wrap break-all p-4 font-mono text-xs leading-relaxed text-toned"
              @scroll="onLogsScroll"
            >
              <div v-if="logsLoading && !logsText" class="flex items-center gap-2 text-muted">
                <UIcon name="i-lucide-loader-2" class="size-3.5 animate-spin" /> Loading logs…
              </div>
              <template v-else>
                {{ logsText }}
                <div
                  v-if="logsError && logsText"
                  class="mt-2 border-t border-error/30 pt-2 text-error"
                >
                  {{ logsDisconnected ? 'Connection lost' : 'Fetch error' }}: {{ logsError }}
                </div>
              </template>
              <div v-if="logsError && !logsText" class="text-error">
                {{ logsError }}
              </div>
            </div>
            <UButton
              v-if="!logsAtBottom"
              color="neutral"
              variant="solid"
              size="xs"
              class="absolute bottom-2 right-4 shadow-lg"
              @click="jumpLogsBottom"
            >
              ↓ Jump to bottom
            </UButton>
          </div>
          <template #footer>
            <div class="flex items-center justify-between text-[10px]">
              <span :class="logsDisconnected ? 'text-error' : 'text-muted'">
                {{ logsDisconnected ? 'Reconnecting…' : 'Auto-refreshing every 2s' }}
              </span>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-refresh-cw"
                size="xs"
                :loading="logsLoading"
                @click="logsTick(consoleExt!.id)"
              />
            </div>
          </template>
        </UCard>
      </template>
    </UModal>
  </UDashboardPanel>
</template>

