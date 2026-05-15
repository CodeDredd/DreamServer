<!--
  Service-Inventar mit Tab-Filter (All / Online / Degraded / Inactive)
  und per-Container CPU/Mem-Spalten. React-Pendant: Dashboard.jsx
  Zeile 1204+ ("Services" section) und buildServiceRows (363).

  Datenquellen:
  * useRepo(Service) — Service-Liste (single source of truth, kommt
    aus SystemRepository via /api/status).
  * useServiceResources() — per-Container CPU/Mem (eigener Endpoint
    /api/services/resources, alle 10 s).
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRepo } from 'pinia-orm'
import Service from '~~/store/models/Service'
import { useServiceResources } from '~/composables/useServiceResources'
import type { TableColumn } from '@nuxt/ui'

type TabKey = 'all' | 'online' | 'degraded' | 'inactive'

const activeTab = ref<TabKey>('all')
const search = ref('')

const services = computed(() => useRepo(Service).orderBy('name').get())
const { byServiceId } = useServiceResources()

interface ServiceRow {
  id: string
  name: string
  status: string
  port?: number
  uptime?: number
  cpuPercent: number | null
  memUsedMb: number | null
  memLimitMb: number | null
  memPercent: number | null
}

const rows = computed<ServiceRow[]>(() => {
  return services.value.map((s) => {
    const sid = s.id || s.name
    const r = byServiceId.value.get(sid)
    const c = r?.container
    return {
      id: sid,
      name: s.name,
      status: s.status,
      port: s.port || undefined,
      uptime: s.uptime || undefined,
      cpuPercent: c ? c.cpu_percent : null,
      memUsedMb: c ? c.memory_used_mb : null,
      memLimitMb: c ? c.memory_limit_mb : null,
      memPercent: c ? c.memory_percent : null,
    }
  })
})

function tabFilter(status: string, tab: TabKey): boolean {
  if (tab === 'all') return true
  if (tab === 'online') return status === 'healthy'
  if (tab === 'degraded') return status === 'degraded' || status === 'unhealthy' || status === 'failed'
  if (tab === 'inactive') return status === 'not_deployed' || status === 'unknown' || status === 'starting'
  return true
}

const filteredRows = computed(() => {
  const q = search.value.trim().toLowerCase()
  return rows.value.filter((r) => {
    if (!tabFilter(r.status, activeTab.value)) return false
    if (q && !(r.name.toLowerCase().includes(q) || r.id.toLowerCase().includes(q))) return false
    return true
  })
})

const counts = computed(() => {
  const all = rows.value
  return {
    all: all.length,
    online: all.filter(r => tabFilter(r.status, 'online')).length,
    degraded: all.filter(r => tabFilter(r.status, 'degraded')).length,
    inactive: all.filter(r => tabFilter(r.status, 'inactive')).length,
  }
})

const tabItems = computed(() => [
  { label: 'Alle', value: 'all' as TabKey, badge: counts.value.all },
  { label: 'Online', value: 'online' as TabKey, badge: counts.value.online },
  { label: 'Degraded', value: 'degraded' as TabKey, badge: counts.value.degraded },
  { label: 'Inaktiv', value: 'inactive' as TabKey, badge: counts.value.inactive },
])

function statusColor(s: string): 'success' | 'warning' | 'error' | 'neutral' {
  if (s === 'healthy') return 'success'
  if (s === 'degraded' || s === 'starting') return 'warning'
  if (s === 'unhealthy' || s === 'failed') return 'error'
  return 'neutral'
}

function memColor(p: number | null): 'success' | 'warning' | 'error' | 'neutral' {
  if (p == null) return 'neutral'
  if (p >= 90) return 'error'
  if (p >= 75) return 'warning'
  return 'success'
}

const columns: TableColumn<ServiceRow>[] = [
  { accessorKey: 'name', header: 'Service' },
  { accessorKey: 'status', header: 'Status' },
  { accessorKey: 'cpuPercent', header: 'CPU', meta: { class: { td: 'tabular-nums' } } },
  { accessorKey: 'memPercent', header: 'Memory', meta: { class: { td: 'tabular-nums w-44' } } },
  { accessorKey: 'port', header: 'Port', meta: { class: { td: 'tabular-nums text-muted' } } },
]
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-base font-semibold text-default">
          Services
        </h2>
        <UInput
          v-model="search"
          icon="i-lucide-search"
          placeholder="Filter…"
          size="sm"
          class="w-full sm:w-64"
        />
      </div>
      <UTabs
        v-model="activeTab"
        :items="tabItems"
        size="sm"
        variant="link"
        class="mt-3 -mb-1"
      />
    </template>

    <UTable
      :data="filteredRows"
      :columns="columns"
      :ui="{ td: 'py-2.5', th: 'text-[10px] uppercase tracking-widest' }"
      empty-state="Keine Services gefunden"
    >
      <template #name-cell="{ row }">
        <div class="min-w-0">
          <p class="font-medium text-default">
            {{ row.original.name }}
          </p>
          <p class="truncate text-xs text-muted">
            {{ row.original.id }}
          </p>
        </div>
      </template>

      <template #status-cell="{ row }">
        <UBadge :color="statusColor(row.original.status)" variant="subtle" size="sm">
          {{ row.original.status }}
        </UBadge>
      </template>

      <template #cpuPercent-cell="{ row }">
        <span v-if="row.original.cpuPercent == null" class="text-muted">—</span>
        <span v-else>{{ row.original.cpuPercent.toFixed(1) }} %</span>
      </template>

      <template #memPercent-cell="{ row }">
        <div v-if="row.original.memPercent == null" class="text-muted">
          —
        </div>
        <div v-else class="flex items-center gap-2">
          <UProgress
            class="w-20"
            :model-value="Math.min(row.original.memPercent, 100)"
            :max="100"
            size="xs"
            :color="memColor(row.original.memPercent)"
          />
          <span class="text-xs text-muted">
            {{ Math.round((row.original.memUsedMb ?? 0)) }} MB
          </span>
        </div>
      </template>

      <template #port-cell="{ row }">
        <span v-if="!row.original.port" class="text-muted">—</span>
        <span v-else>:{{ row.original.port }}</span>
      </template>
    </UTable>
  </UCard>
</template>

