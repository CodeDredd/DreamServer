<!--
  EnrichmentRunsTable — letzte Läufe der n8n-Anreicherungs-Workflows
  (Asset-Behaviour, Source-Reliability). Quelle:
  /api/finance-guru/enrichment/runs.

  Diese Tabelle macht für den Operator sichtbar, dass die Workflows
  laufen, was sie analysiert haben und ob es Fehler gab. Genau das,
  was der User mit "Logs über regelmäßige Updates" gemeint hat.
-->
<script setup lang="ts">
import { computed, h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { FinanceEnrichmentRun } from '~/types/api'
import { relTime } from '~/utils/format'

const props = defineProps<{
  runs: FinanceEnrichmentRun[]
}>()

const UBadge = resolveComponent('UBadge')

const lastByWorkflow = computed(() => {
  const seen: Record<string, FinanceEnrichmentRun> = {}
  for (const r of props.runs) {
    if (!seen[r.workflow] || seen[r.workflow]!.ts < r.ts) seen[r.workflow] = r
  }
  return seen
})

const columns: TableColumn<FinanceEnrichmentRun>[] = [
  {
    accessorKey: 'ts',
    header: 'Zeit',
    cell: ({ row }) => h(
      'div',
      { class: 'text-xs' },
      [
        h('div', { class: 'text-default' }, relTime(row.original.ts)),
        h('div', { class: 'text-muted' }, new Date(row.original.ts).toLocaleString()),
      ],
    ),
  },
  {
    accessorKey: 'workflow',
    header: 'Workflow',
    cell: ({ row }) => h(UBadge, {
      color: row.original.workflow === 'asset_behaviour' ? 'primary' : 'secondary',
      variant: 'subtle',
      size: 'xs',
    }, () => row.original.workflow),
  },
  {
    accessorKey: 'target',
    header: 'Target',
    cell: ({ row }) => h('span', { class: 'font-mono text-xs text-default' }, row.original.target || '–'),
  },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ row }) => {
      const map: Record<string, 'success' | 'warning' | 'error' | 'neutral'> = {
        ok: 'success', skipped: 'neutral', error: 'error',
      }
      return h(UBadge, {
        color: map[row.original.status] || 'neutral',
        variant: 'subtle',
        size: 'xs',
      }, () => row.original.status)
    },
  },
  {
    accessorKey: 'duration_ms',
    header: 'Dauer',
    cell: ({ row }) => h('span', { class: 'text-xs text-muted tabular-nums' },
      row.original.duration_ms ? `${(row.original.duration_ms / 1000).toFixed(1)}s` : '–'),
  },
  {
    accessorKey: 'note',
    header: 'Notiz',
    cell: ({ row }) => h('span', { class: 'text-xs text-muted line-clamp-2' }, row.original.note || ''),
  },
]
</script>

<template>
  <UCard :ui="{ body: 'p-0' }">
    <template #header>
      <div class="flex flex-wrap items-center gap-3">
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-database-zap" class="size-3.5 text-muted" />
          <h4 class="text-sm font-semibold">
            Enrichment-Workflows
          </h4>
        </div>
        <div class="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <UBadge
            :color="lastByWorkflow.asset_behaviour?.status === 'error' ? 'error' : 'primary'"
            variant="subtle" size="xs"
          >
            asset_behaviour:
            {{ lastByWorkflow.asset_behaviour ? relTime(lastByWorkflow.asset_behaviour.ts) : 'kein Lauf' }}
          </UBadge>
          <UBadge
            :color="lastByWorkflow.source_reliability?.status === 'error' ? 'error' : 'secondary'"
            variant="subtle" size="xs"
          >
            source_reliability:
            {{ lastByWorkflow.source_reliability ? relTime(lastByWorkflow.source_reliability.ts) : 'kein Lauf' }}
          </UBadge>
        </div>
      </div>
    </template>
    <div v-if="!runs.length" class="px-5 py-8 text-center text-sm text-muted">
      Noch keine Enrichment-Läufe — importiere die n8n-Workflows
      <code class="font-mono">09-finance-asset-behaviour.json</code> und
      <code class="font-mono">10-finance-source-reliability.json</code>.
    </div>
    <UTable
      v-else
      :data="runs"
      :columns="columns"
      sticky
      class="max-h-[360px]"
      :ui="{ td: 'py-1.5', th: 'py-2 text-xs' }"
    />
  </UCard>
</template>

