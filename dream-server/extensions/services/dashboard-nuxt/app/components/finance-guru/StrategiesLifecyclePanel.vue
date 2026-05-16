<!--
  Phase F: StrategiesLifecyclePanel — Live / Proposed / Archived / Retired
  in einem UTabs-Header, dazu ein Leaderboard-Tab (7d) und ein
  Detail-UModal mit den letzten Audit-Transitions je Strategie.
-->
<script setup lang="ts">
import { computed, h, ref, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import { useFinanceGuru } from '~/composables/useFinanceGuru'
import { formatPct, pnlToneClass, relTime } from '~/utils/format'
import type {
  FinanceAuditRow,
  FinanceLeaderboardRow,
  FinanceLifecycleRow,
} from '~/types/api'

const fg = useFinanceGuru()
const UBadge = resolveComponent('UBadge')
const UButton = resolveComponent('UButton')

const STATUS_TONE: Record<string, string> = {
  live:     'success',
  proposed: 'info',
  archived: 'neutral',
  retired:  'warning',
}

const tab = ref<'live' | 'proposed' | 'archived' | 'retired' | 'leaderboard'>('live')
const tabItems = computed(() => [
  { value: 'live',        label: 'Live',        icon: 'i-lucide-play',
    badge: countBy('live') },
  { value: 'proposed',    label: 'Proposed',    icon: 'i-lucide-hourglass',
    badge: countBy('proposed') },
  { value: 'archived',    label: 'Archived',    icon: 'i-lucide-archive',
    badge: countBy('archived') },
  { value: 'retired',     label: 'Retired',     icon: 'i-lucide-power-off',
    badge: countBy('retired') },
  { value: 'leaderboard', label: 'Leaderboard', icon: 'i-lucide-trophy',
    badge: fg.leaderboard.value.length },
])
function countBy(status: string): number {
  return fg.lifecycle.value.filter(r => r.status === status).length
}
const filteredRows = computed<FinanceLifecycleRow[]>(() =>
  tab.value === 'leaderboard'
    ? []
    : fg.lifecycle.value.filter(r => r.status === tab.value),
)

// Detail modal state
const showAuditModal = ref(false)
const auditSelected = ref<FinanceLifecycleRow | null>(null)
const auditRows = ref<FinanceAuditRow[]>([])
const auditLoading = ref(false)

async function openAudit(row: FinanceLifecycleRow) {
  auditSelected.value = row
  showAuditModal.value = true
  auditLoading.value = true
  try {
    auditRows.value = await fg.listAudits(row.name, 30)
  }
  finally {
    auditLoading.value = false
  }
}

const lifecycleColumns: TableColumn<FinanceLifecycleRow>[] = [
  {
    accessorKey: 'name',
    header: 'Name',
    cell: ({ row }) => h('div', { class: 'flex items-center gap-2' }, [
      h('span', { class: 'font-mono text-xs' }, row.original.name),
      h(UBadge, {
        size: 'xs', variant: 'subtle',
        color: row.original.kind === 'generated' ? 'primary' : 'neutral',
      }, () => row.original.kind),
    ]),
  },
  {
    accessorKey: 'bt_pnl_pct',
    header: 'Backtest PnL',
    cell: ({ row }) => {
      const v = row.original.bt_pnl_pct
      return h('div', { class: ['text-xs tabular-nums', pnlToneClass(v)] }, [
        v == null ? '—' : formatPct(v, 2),
        h('span', { class: 'ml-1 text-muted' },
          `(${row.original.bt_n_trades ?? 0} tr)`),
      ])
    },
  },
  {
    accessorKey: 'created_at',
    header: 'Created',
    cell: ({ row }) => h('span', { class: 'text-xs text-muted' },
      relTime(row.original.created_at || '')),
  },
  {
    accessorKey: 'retire_reason',
    header: 'Note',
    cell: ({ row }) => h('span',
      { class: 'text-xs text-muted line-clamp-1 max-w-md',
        title: row.original.retire_reason || '' },
      row.original.retire_reason || '—'),
  },
  {
    id: 'actions',
    header: '',
    cell: ({ row }) => h(UButton, {
      icon: 'i-lucide-history',
      size: 'xs', variant: 'ghost', color: 'neutral',
      title: 'Audit-Verlauf öffnen',
      onClick: () => openAudit(row.original),
    }),
  },
]

const leaderboardColumns: TableColumn<FinanceLeaderboardRow>[] = [
  {
    id: 'rank',
    header: '#',
    cell: ({ row }) => h('span', { class: 'tabular-nums text-muted' },
      String((row.index ?? 0) + 1)),
  },
  {
    accessorKey: 'name',
    header: 'Strategy',
    cell: ({ row }) => h('div', { class: 'flex items-center gap-2' }, [
      h('span', { class: 'font-mono text-xs' }, row.original.name),
      h(UBadge, {
        size: 'xs', variant: 'subtle',
        color: STATUS_TONE[row.original.status] ?? 'neutral',
      }, () => row.original.status),
    ]),
  },
  {
    accessorKey: 'window_pnl_pct',
    header: 'PnL (window)',
    cell: ({ row }) => {
      const v = row.original.window_pnl_pct
      return h('span',
        { class: ['text-xs tabular-nums font-semibold', pnlToneClass(v)] },
        v == null ? '—' : formatPct(v, 2))
    },
  },
  {
    accessorKey: 'window_cycles',
    header: 'Cycles',
    cell: ({ row }) => h('span', { class: 'text-xs tabular-nums text-muted' },
      String(row.original.window_cycles ?? 0)),
  },
  {
    accessorKey: 'retire_reason',
    header: 'Note',
    cell: ({ row }) => h('span',
      { class: 'text-xs text-muted line-clamp-1 max-w-md' },
      row.original.retire_reason || '—'),
  },
]

const TRANSITION_TONE: Record<string, string> = {
  register: 'neutral',
  propose:  'info',
  promote:  'success',
  retire:   'warning',
  archive:  'neutral',
}
</script>

<template>
  <UCard variant="subtle" :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-git-branch" class="size-4 text-primary" />
          <h3 class="text-sm font-semibold">
            Strategy-Lifecycle
          </h3>
          <UBadge variant="subtle" size="xs" color="neutral">
            {{ fg.lifecycle.value.length }} total
          </UBadge>
        </div>
        <div v-if="fg.dslCatalog.value" class="flex items-center gap-3 text-xs text-muted">
          <span class="flex items-center gap-1">
            <UIcon name="i-lucide-shield" class="size-3" />
            Gate: {{ fg.dslCatalog.value.gate.min_backtest_pct }}% /
            {{ fg.dslCatalog.value.gate.min_backtest_trades }}tr /
            {{ fg.dslCatalog.value.gate.backtest_days }}d
          </span>
          <span class="flex items-center gap-1">
            <UIcon name="i-lucide-gauge" class="size-3" />
            Quota: {{ fg.dslCatalog.value.gate.quota_used }} /
            {{ fg.dslCatalog.value.gate.quota_per_window }}
            ({{ fg.dslCatalog.value.gate.quota_window_days }}d)
          </span>
        </div>
      </div>
    </template>
    <UTabs v-model="tab" :items="tabItems" variant="link" size="sm"
           :ui="{ list: 'px-4 border-b border-default', trigger: 'gap-2 text-xs' }"
    >
      <template #default="{ item }">
        <UIcon :name="item.icon" class="size-3.5" />
        <span>{{ item.label }}</span>
        <UBadge v-if="(item.badge ?? 0) > 0"
                variant="subtle" size="xs" color="neutral"
        >
          {{ item.badge }}
        </UBadge>
      </template>
    </UTabs>
    <div v-if="tab !== 'leaderboard'">
      <div v-if="!filteredRows.length" class="px-5 py-8 text-center text-sm text-muted">
        Keine Strategien im Status <code>{{ tab }}</code>.
      </div>
      <UTable v-else
              :data="filteredRows"
              :columns="lifecycleColumns"
              :ui="{ td: 'py-1.5', th: 'py-2 text-xs' }"
      />
    </div>
    <div v-else>
      <div v-if="!fg.leaderboard.value.length" class="px-5 py-8 text-center text-sm text-muted">
        Noch keine Leaderboard-Daten — der Backtest-Worker hat noch keine vollständige Window-Periode.
      </div>
      <UTable v-else
              :data="fg.leaderboard.value"
              :columns="leaderboardColumns"
              :ui="{ td: 'py-1.5', th: 'py-2 text-xs' }"
      />
    </div>
  </UCard>

  <UModal v-model:open="showAuditModal" :title="auditSelected?.name || 'Audit'"
          :description="`Lifecycle-Transitionen — kind=${auditSelected?.kind}, status=${auditSelected?.status}`"
          :ui="{ content: 'max-w-2xl' }"
  >
    <template #body>
      <div v-if="auditLoading" class="space-y-2">
        <USkeleton class="h-6 w-full" />
        <USkeleton class="h-6 w-full" />
        <USkeleton class="h-6 w-3/4" />
      </div>
      <div v-else-if="!auditRows.length" class="py-6 text-center text-sm text-muted">
        Keine Audit-Einträge.
      </div>
      <ol v-else class="space-y-3">
        <li v-for="a in auditRows" :key="a.id"
            class="flex items-start gap-3 rounded-md border border-default bg-elevated/30 p-2"
        >
          <UBadge variant="subtle" size="xs"
                  :color="TRANSITION_TONE[a.transition] ?? 'neutral'"
          >
            {{ a.transition }}
          </UBadge>
          <div class="min-w-0 flex-1">
            <div class="text-xs text-muted">
              {{ relTime(a.ts) }}
              <span v-if="a.from_status || a.to_status" class="ml-1 font-mono">
                {{ a.from_status || '∅' }} → {{ a.to_status || '∅' }}
              </span>
              <span v-if="a.actor" class="ml-1">· by {{ a.actor }}</span>
              <span v-if="a.pnl_pct != null" class="ml-1"
                    :class="pnlToneClass(a.pnl_pct)"
              >
                · {{ formatPct(a.pnl_pct, 2) }}
              </span>
              <span v-if="a.n_cycles != null" class="ml-1">
                · {{ a.n_cycles }} cycles
              </span>
            </div>
            <div v-if="a.note" class="mt-0.5 text-xs text-default">
              {{ a.note }}
            </div>
          </div>
        </li>
      </ol>
    </template>
  </UModal>
</template>

