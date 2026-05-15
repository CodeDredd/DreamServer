<!--
  Integrations / ServiceMap (Phase 4 Welle B.4). Pendant zu
  dashboard/src/pages/ServiceMap.jsx (~370 LoC). Layered SVG-Topology
  (core / middleware / user-facing / other) aus /api/status mit
  bekannten KNOWN_EDGES; Detail-Panel rechts beim Klick auf einen Node.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  EDGE_META,
  LAYERS,
  LAYER_LABELS,
  NODE_H,
  NODE_W,
  arrowMarkerId,
  edgePath,
  statusMeta,
  useServiceTopology,
  type TopoEdge,
  type TopoNode,
} from '~/composables/useServiceTopology'

definePageMeta({ layout: 'default' })

const { topology, loading, error, layout, counts, edgeLabels, refresh }
  = useServiceTopology()

const selectedId = ref<string | null>(null)
const selectedNode = computed<TopoNode | null>(
  () => topology.value.nodes.find(n => n.id === selectedId.value) ?? null,
)

const upstream = computed<TopoEdge[]>(() => {
  if (!selectedNode.value) return []
  return topology.value.edges.filter(e => e.target === selectedNode.value!.id)
})
const downstream = computed<TopoEdge[]>(() => {
  if (!selectedNode.value) return []
  return topology.value.edges.filter(e => e.source === selectedNode.value!.id)
})
const selectedServiceUrl = computed(() => {
  const n = selectedNode.value
  if (!n || !n.port || typeof window === 'undefined') return null
  return `http://${window.location.hostname}:${n.port}`
})

function nodeNameTrim(name: string): string {
  return name.length > 18 ? `${name.slice(0, 17)}…` : name
}
</script>

<template>
  <UDashboardPanel id="integrations">
    <template #header>
      <UDashboardNavbar
        title="Integrations"
        :description="`${topology.nodes.length} Services im Layered-Topology-Graph`"
        icon="i-lucide-git-branch"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UBadge color="success" variant="subtle" size="sm" icon="i-lucide-radio">
            live · 10s
          </UBadge>
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
      <div class="space-y-4">
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-alert-triangle"
          title="Topology-Daten nicht verfügbar"
          :description="error"
        />

        <!-- Status counts -->
        <div class="flex flex-wrap items-center gap-4 text-xs">
          <span class="text-muted">Status:</span>
          <span class="inline-flex items-center gap-1.5 text-success">
            <span class="size-2 rounded-full bg-success" /> {{ counts.healthy }} healthy
          </span>
          <span v-if="counts.degraded > 0" class="inline-flex items-center gap-1.5 text-warning">
            <span class="size-2 rounded-full bg-warning" /> {{ counts.degraded }} degraded
          </span>
          <span v-if="counts.down > 0" class="inline-flex items-center gap-1.5 text-error">
            <span class="size-2 rounded-full bg-error" /> {{ counts.down }} down
          </span>
          <span v-if="counts.other > 0" class="inline-flex items-center gap-1.5 text-muted">
            <span class="size-2 rounded-full bg-muted" /> {{ counts.other }} other
          </span>
        </div>

        <!-- SVG canvas + detail panel -->
        <UCard :ui="{ body: 'p-0 relative' }">
          <div v-if="loading && !topology.nodes.length" class="p-12 text-center text-sm text-muted">
            <UIcon name="i-lucide-loader-2" class="mx-auto mb-2 size-6 animate-spin" />
            Lade Topology…
          </div>
          <div v-else class="relative min-h-[70vh] overflow-auto">
            <svg
              :width="layout.svgWidth"
              :height="layout.svgHeight"
              :viewBox="`0 0 ${layout.svgWidth} ${layout.svgHeight}`"
              class="mx-auto block"
            >
              <defs>
                <filter id="node-shadow" x="-25%" y="-60%" width="150%" height="230%">
                  <feDropShadow dx="0" dy="2" stdDeviation="10" flood-color="#000" flood-opacity="0.7" />
                </filter>
                <marker
                  v-for="(color, label) in EDGE_META"
                  :id="arrowMarkerId(String(label))"
                  :key="String(label)"
                  markerWidth="7"
                  markerHeight="5"
                  refX="7"
                  refY="2.5"
                  orient="auto"
                >
                  <path d="M 0 0 L 7 2.5 L 0 5 Z" :fill="color" fill-opacity="0.85" />
                </marker>
              </defs>

              <!-- Layer labels -->
              <template v-for="layer in LAYERS" :key="layer">
                <text
                  v-if="layout.layerY[layer] != null"
                  x="32"
                  :y="layout.layerY[layer]! + NODE_H / 2"
                  fill="#71717a"
                  font-size="10"
                  font-weight="700"
                >
                  {{ LAYER_LABELS[layer] }}
                </text>
              </template>

              <!-- Edges -->
              <template v-for="edge in topology.edges" :key="`${edge.source}-${edge.target}`">
                <path
                  v-if="layout.positions[edge.source] && layout.positions[edge.target]"
                  :d="edgePath(layout.positions[edge.source]!, layout.positions[edge.target]!)"
                  fill="none"
                  :stroke="EDGE_META[edge.label] || '#6b7280'"
                  stroke-width="1.8"
                  :stroke-opacity="edge.status === 'healthy' ? 0.72 : 0.32"
                  :stroke-dasharray="edge.status === 'healthy' ? undefined : '5 4'"
                  :marker-end="`url(#${arrowMarkerId(edge.label)})`"
                />
              </template>

              <!-- Nodes -->
              <g
                v-for="node in topology.nodes"
                :key="node.id"
                class="cursor-pointer"
                @click="selectedId = node.id"
              >
                <template v-if="layout.positions[node.id]">
                  <rect
                    v-if="selectedId === node.id"
                    :x="layout.positions[node.id]!.x - 4"
                    :y="layout.positions[node.id]!.y - 4"
                    :width="NODE_W + 8"
                    :height="NODE_H + 8"
                    rx="14"
                    fill="none"
                    :stroke="statusMeta(node.status).color"
                    stroke-width="2"
                  />
                  <rect
                    :x="layout.positions[node.id]!.x"
                    :y="layout.positions[node.id]!.y"
                    :width="NODE_W"
                    :height="NODE_H"
                    rx="12"
                    fill="#18181b"
                    stroke="#3f3f46"
                  />
                  <circle
                    :cx="layout.positions[node.id]!.x + 15"
                    :cy="layout.positions[node.id]!.y + 25"
                    r="4"
                    :fill="statusMeta(node.status).color"
                  />
                  <text
                    :x="layout.positions[node.id]!.x + 27"
                    :y="layout.positions[node.id]!.y + 29"
                    fill="#f4f4f5"
                    font-size="12"
                    font-weight="700"
                  >
                    {{ nodeNameTrim(node.name) }}
                  </text>
                  <text
                    :x="layout.positions[node.id]!.x + 15"
                    :y="layout.positions[node.id]!.y + 47"
                    fill="#71717a"
                    font-size="10"
                    font-family="monospace"
                  >
                    :{{ node.port }}
                  </text>
                  <text
                    :x="layout.positions[node.id]!.x + NODE_W - 10"
                    :y="layout.positions[node.id]!.y + 47"
                    text-anchor="end"
                    font-size="9"
                    :fill="statusMeta(node.status).color"
                  >
                    {{ node.status }}
                  </text>
                </template>
              </g>
            </svg>

            <!-- Edge legend strip -->
            <div class="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-default px-4 py-3">
              <span class="text-xs font-medium text-muted">Connections:</span>
              <span
                v-for="label in edgeLabels"
                :key="label"
                class="inline-flex items-center gap-1.5 text-xs text-muted"
              >
                <span
                  class="inline-block size-2 rounded-full"
                  :style="{ background: EDGE_META[label] || '#6b7280' }"
                />
                {{ label }}
              </span>
            </div>

            <!-- Detail panel (overlay) -->
            <div
              v-if="selectedNode"
              class="absolute right-4 top-4 z-10 w-72 overflow-hidden rounded-xl border border-default bg-default shadow-2xl"
            >
              <div class="flex items-center justify-between border-b border-default px-4 py-3">
                <div class="flex items-center gap-2">
                  <span
                    class="size-2.5 rounded-full"
                    :class="statusMeta(selectedNode.status).dot"
                  />
                  <span class="text-sm font-semibold text-default">{{ selectedNode.name }}</span>
                </div>
                <UButton
                  color="neutral"
                  variant="ghost"
                  icon="i-lucide-x"
                  size="xs"
                  square
                  @click="selectedId = null"
                />
              </div>
              <div class="space-y-3 px-4 py-3 text-xs">
                <div class="flex justify-between">
                  <span class="text-muted">Status</span>
                  <span :class="statusMeta(selectedNode.status).text">{{ selectedNode.status }}</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-muted">Port</span>
                  <span class="font-mono text-default">{{ selectedNode.port || '—' }}</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-muted">Layer</span>
                  <span class="text-default">{{ selectedNode.category }}</span>
                </div>
                <div v-if="upstream.length">
                  <p class="mb-1 text-muted">
                    Used by:
                  </p>
                  <div class="space-y-1">
                    <div
                      v-for="e in upstream"
                      :key="`${e.source}-${e.target}`"
                      class="flex items-center gap-1.5 text-default"
                    >
                      <span :style="{ color: EDGE_META[e.label] || '#6b7280' }">●</span>
                      {{ e.source }}
                      <span class="ml-auto text-muted">({{ e.label }})</span>
                    </div>
                  </div>
                </div>
                <div v-if="downstream.length">
                  <p class="mb-1 text-muted">
                    Depends on:
                  </p>
                  <div class="space-y-1">
                    <div
                      v-for="e in downstream"
                      :key="`${e.source}-${e.target}`"
                      class="flex items-center gap-1.5 text-default"
                    >
                      <span :style="{ color: EDGE_META[e.label] || '#6b7280' }">●</span>
                      {{ e.target }}
                      <span class="ml-auto text-muted">({{ e.label }})</span>
                    </div>
                  </div>
                </div>
                <a
                  v-if="selectedServiceUrl"
                  :href="selectedServiceUrl"
                  target="_blank"
                  rel="noreferrer"
                  class="flex items-center gap-1.5 text-primary hover:underline"
                >
                  <UIcon name="i-lucide-external-link" class="size-3" />
                  Open service
                </a>
              </div>
            </div>
          </div>
        </UCard>
      </div>
    </template>
  </UDashboardPanel>
</template>

