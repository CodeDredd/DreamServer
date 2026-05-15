// Composable für die Integrations-Page (Welle B.4 — Pendant zu
// dashboard/src/pages/ServiceMap.jsx). Baut aus dem /api/status-Feed
// einen Layered-Topology-Graph (core / middleware / user-facing /
// other) inkl. statischer KNOWN_EDGES und SVG-Layout-Helfern.

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { usePolling } from '~/composables/usePolling'
import { dreamFetch } from '~/composables/useApi'
import type { ServiceSummary, SystemStatus } from '~/types/api'

// ---------- Layout-Konstanten -------------------------------------------
export const NODE_W = 170
export const NODE_H = 64
export const LABEL_W = 210
export const LAYER_GAP = 190
export const NODE_GAP = 42
export const MIN_W = 1080
export const MIN_H = 720
export const POLL_INTERVAL = 10_000

export const LAYERS = ['core', 'middleware', 'user-facing', 'other'] as const
export type LayerId = typeof LAYERS[number]

export const LAYER_LABELS: Record<LayerId, string> = {
  'core': 'CORE',
  'middleware': 'MIDDLEWARE',
  'user-facing': 'USER FACING',
  'other': 'OTHER',
}

const CATEGORY_MAP: Record<string, LayerId> = {
  'llama-server': 'core',
  'qdrant': 'core',
  'searxng': 'core',
  'embeddings': 'core',
  'whisper': 'core',
  'tts': 'core',
  'litellm': 'middleware',
  'dashboard-api': 'middleware',
  'token-spy': 'middleware',
  'privacy-shield': 'middleware',
  'langfuse': 'middleware',
  'ape': 'middleware',
  'open-webui': 'user-facing',
  'perplexica': 'user-facing',
  'n8n': 'user-facing',
  'openclaw': 'user-facing',
  'dashboard': 'user-facing',
  'comfyui': 'user-facing',
  'dreamforge': 'user-facing',
  'opencode': 'user-facing',
}

const NAME_TO_ID: Record<string, string> = {
  'APE (Agent Policy Engine)': 'ape',
  'ComfyUI (Image Generation)': 'comfyui',
  'Dashboard (Control Center)': 'dashboard',
  'Dashboard API (System Status)': 'dashboard-api',
  'DreamForge': 'dreamforge',
  'Kokoro (TTS)': 'tts',
  'LiteLLM (API Gateway)': 'litellm',
  'llama-server (LLM Inference)': 'llama-server',
  'n8n (Workflows)': 'n8n',
  'Open WebUI (Chat)': 'open-webui',
  'OpenClaw (Agents)': 'openclaw',
  'OpenCode (IDE)': 'opencode',
  'Perplexica (Deep Research)': 'perplexica',
  'Privacy Shield (PII Protection)': 'privacy-shield',
  'Qdrant (Vector DB)': 'qdrant',
  'SearXNG (Web Search)': 'searxng',
  'TEI (Embeddings)': 'embeddings',
  'Token Spy (Usage Monitor)': 'token-spy',
  'Whisper (STT)': 'whisper',
}

// source -> target -> kind
const KNOWN_EDGES: Array<[string, string, string]> = [
  ['open-webui', 'litellm', 'LLM proxy'],
  ['litellm', 'llama-server', 'inference'],
  ['perplexica', 'searxng', 'search'],
  ['perplexica', 'litellm', 'LLM proxy'],
  ['n8n', 'litellm', 'LLM proxy'],
  ['n8n', 'qdrant', 'vector store'],
  ['openclaw', 'litellm', 'LLM proxy'],
  ['openclaw', 'qdrant', 'vector store'],
  ['litellm', 'langfuse', 'observability'],
  ['qdrant', 'embeddings', 'embeddings'],
  ['open-webui', 'whisper', 'voice input'],
  ['open-webui', 'tts', 'voice output'],
  ['dashboard', 'dashboard-api', 'API'],
  ['dashboard-api', 'llama-server', 'API'],
  ['token-spy', 'litellm', 'intercept'],
  ['privacy-shield', 'litellm', 'privacy'],
  ['comfyui', 'open-webui', 'API'],
  ['ape', 'litellm', 'LLM proxy'],
  ['dreamforge', 'litellm', 'LLM proxy'],
  ['dreamforge', 'searxng', 'search'],
]

export const EDGE_META: Record<string, string> = {
  'inference': '#a855f7',
  'LLM proxy': '#3b82f6',
  'search': '#f97316',
  'vector store': '#06b6d4',
  'embeddings': '#14b8a6',
  'voice input': '#ec4899',
  'voice output': '#ec4899',
  'API': '#6366f1',
  'intercept': '#f59e0b',
  'observability': '#84cc16',
  'privacy': '#f43f5e',
}

export interface NodeStatusMeta {
  color: string
  text: string
  dot: string
}

export const STATUS_META: Record<string, NodeStatusMeta> = {
  healthy: { color: '#22c55e', text: 'text-success', dot: 'bg-success' },
  degraded: { color: '#eab308', text: 'text-warning', dot: 'bg-warning' },
  unhealthy: { color: '#ef4444', text: 'text-error', dot: 'bg-error' },
  down: { color: '#ef4444', text: 'text-error', dot: 'bg-error' },
  not_deployed: { color: '#6b7280', text: 'text-muted', dot: 'bg-muted' },
  unknown: { color: '#6b7280', text: 'text-muted', dot: 'bg-muted' },
}

export function statusMeta(status: string): NodeStatusMeta {
  return STATUS_META[status] || STATUS_META.unknown!
}

function slugServiceName(name: string): string {
  return String(name || '')
    .toLowerCase()
    .replace(/\([^)]*\)/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

interface ServiceWithExtras extends ServiceSummary {
  external_port?: number
  service_id?: string
  key?: string
}

function resolveServiceId(service: ServiceWithExtras): string {
  const explicit = service.id || service.service_id || service.key
  if (explicit) return explicit
  return NAME_TO_ID[service.name] || slugServiceName(service.name)
}

export interface TopoNode {
  id: string
  name: string
  status: string
  port: number | string
  category: LayerId
}

export interface TopoEdge {
  source: string
  target: string
  label: string
  status: 'healthy' | 'degraded'
}

export interface Topology {
  nodes: TopoNode[]
  edges: TopoEdge[]
}

export function buildTopology(statusData: SystemStatus | null): Topology {
  const services = Array.isArray(statusData?.services) ? (statusData!.services as ServiceWithExtras[]) : []
  const nodes: TopoNode[] = services
    .map((service): TopoNode | null => {
      const id = resolveServiceId(service)
      if (!id) return null
      return {
        id,
        name: service.name || id,
        status: service.status || 'unknown',
        port: service.external_port || service.port || '',
        category: CATEGORY_MAP[id] || 'other',
      }
    })
    .filter((n): n is TopoNode => n !== null)

  const nodeById = new Map(nodes.map(n => [n.id, n]))
  const edges: TopoEdge[] = KNOWN_EDGES
    .filter(([s, t]) => nodeById.has(s) && nodeById.has(t))
    .map(([s, t, label]) => {
      const sn = nodeById.get(s)!
      const tn = nodeById.get(t)!
      const status: 'healthy' | 'degraded'
        = sn.status === 'healthy' && tn.status === 'healthy' ? 'healthy' : 'degraded'
      return { source: s, target: t, label, status }
    })

  return { nodes, edges }
}

export interface LayoutResult {
  positions: Record<string, { x: number, y: number }>
  layerY: Partial<Record<LayerId, number>>
  svgWidth: number
  svgHeight: number
}

export function computeLayout(nodes: TopoNode[]): LayoutResult {
  const rows: Record<LayerId, TopoNode[]> = {
    'core': [], 'middleware': [], 'user-facing': [], 'other': [],
  }
  for (const n of nodes) rows[n.category].push(n)
  for (const r of Object.values(rows)) r.sort((a, b) => a.name.localeCompare(b.name))

  const maxCount = Math.max(1, ...Object.values(rows).map(r => r.length))
  const svgWidth = Math.max(MIN_W, LABEL_W + maxCount * NODE_W + (maxCount - 1) * NODE_GAP + 120)
  const positions: LayoutResult['positions'] = {}
  const layerY: LayoutResult['layerY'] = {}
  let y = 80

  for (const layer of LAYERS) {
    const row = rows[layer]
    if (row.length === 0) continue
    const rowWidth = row.length * NODE_W + Math.max(0, row.length - 1) * NODE_GAP
    const x0 = LABEL_W + Math.max(40, (svgWidth - LABEL_W - rowWidth) / 2)
    row.forEach((node, idx) => {
      positions[node.id] = { x: x0 + idx * (NODE_W + NODE_GAP), y }
    })
    layerY[layer] = y
    y += LAYER_GAP
  }

  return { positions, layerY, svgWidth, svgHeight: Math.max(MIN_H, y + 40) }
}

export function edgePath(
  source: { x: number, y: number },
  target: { x: number, y: number },
): string {
  const sx = source.x + NODE_W / 2
  const sy = source.y + (source.y > target.y ? 0 : NODE_H)
  const tx = target.x + NODE_W / 2
  const ty = target.y + (source.y > target.y ? NODE_H : 0)
  const midY = (sy + ty) / 2
  return `M ${sx} ${sy} L ${sx} ${midY} L ${tx} ${midY} L ${tx} ${ty}`
}

export function arrowMarkerId(label: string): string {
  return `arrow-${label.replaceAll(' ', '-')}`
}

// ---------- Composable -------------------------------------------------
const topology: Ref<Topology> = ref({ nodes: [], edges: [] })
const loading = ref(true)
const error: Ref<string | null> = ref(null)
let started = false

async function fetchTopology() {
  try {
    const data = await dreamFetch<SystemStatus>('/api/status')
    topology.value = buildTopology(data)
    error.value = null
  }
  catch (err: unknown) {
    error.value = (err as Error).message
  }
  finally {
    loading.value = false
  }
}

export function useServiceTopology(): {
  topology: Ref<Topology>
  loading: Ref<boolean>
  error: Ref<string | null>
  layout: ComputedRef<LayoutResult>
  counts: ComputedRef<{ healthy: number, degraded: number, down: number, other: number }>
  edgeLabels: ComputedRef<string[]>
  refresh: () => Promise<void>
} {
  if (!started) {
    started = true
    usePolling(fetchTopology, POLL_INTERVAL)
  }
  const layout = computed(() => computeLayout(topology.value.nodes))
  const counts = computed(() => ({
    healthy: topology.value.nodes.filter(n => n.status === 'healthy').length,
    degraded: topology.value.nodes.filter(n => n.status === 'degraded').length,
    down: topology.value.nodes.filter(n => n.status === 'down' || n.status === 'unhealthy').length,
    other: topology.value.nodes.filter(n => !['healthy', 'degraded', 'down', 'unhealthy'].includes(n.status)).length,
  }))
  const edgeLabels = computed(() => [...new Set(topology.value.edges.map(e => e.label))])
  return { topology, loading, error, layout, counts, edgeLabels, refresh: fetchTopology }
}

