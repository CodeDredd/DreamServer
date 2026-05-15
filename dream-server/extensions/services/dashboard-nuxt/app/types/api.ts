// API-Typen — abgeleitet aus den React-Hooks der Bestands-Variante
// (`dashboard/src/hooks/`) sowie den Routern unter
// `dashboard-api/routers/`. Werden Schritt für Schritt verfeinert,
// sobald die jeweiligen Pages migriert sind (Phase 4 Wellen A–D).

// ---------- /api/status ---------------------------------------------------

export interface GpuSummary {
  name: string
  vramUsed: number
  vramTotal: number
  utilization: number
  temperature: number
  memoryType?: string
  backend?: 'amd' | 'nvidia' | 'intel' | 'apple' | string
  gpu_count?: number
  powerDraw?: number
  memoryLabel?: string
}

export interface ServiceSummary {
  id?: string
  name: string
  status: 'healthy' | 'unhealthy' | 'starting' | 'not_deployed' | 'unknown' | string
  port?: number
  uptime?: number
}

export interface ModelSummary {
  name: string
  tokensPerSecond?: number
  contextLength?: number
}

export interface BootstrapStatus {
  active: boolean
  model?: string
  percent?: number
  bytesDownloaded?: number
  bytesTotal?: number
  speedMbps?: number
  eta?: number
}

export interface RamInfo {
  used_gb: number
  total_gb: number
  percent?: number
}

export interface SystemStatus {
  gpu: GpuSummary | null
  ram?: RamInfo | null
  services: ServiceSummary[]
  model?: ModelSummary | null
  bootstrap?: BootstrapStatus | null
  uptime: number
  version?: string
  tier?: string
}

// ---------- /api/version --------------------------------------------------

export interface VersionInfo {
  current: string
  latest?: string
  update_available?: boolean
  release_notes?: string
}

// ---------- /api/setup/status / complete ---------------------------------

export interface SetupStatus {
  first_run: boolean
  completed_at?: string
  /** Operator-supplied wizard answers, if any */
  config?: Record<string, unknown>
}

// ---------- /api/gpu/* ----------------------------------------------------

export interface GpuDetailed {
  gpus: Array<{
    index: number
    name: string
    vendor: string
    vramTotal: number
    vramUsed: number
    utilization: number
    temperature: number
    powerDraw?: number
    powerLimit?: number
  }>
}

export interface GpuHistorySample {
  t: number
  utilization: number
  vramUsed: number
  temperature: number
}

export interface GpuHistory {
  samples: GpuHistorySample[]
  windowSec: number
}

export interface GpuTopologyEdge {
  from: number
  to: number
  link: 'pcie' | 'nvlink' | 'sli' | 'unknown' | string
  bandwidth?: number
}

export interface GpuTopology {
  nodes: Array<{ index: number, name: string }>
  edges: GpuTopologyEdge[]
}

// ---------- /api/models ---------------------------------------------------

export type ModelStatus = 'loaded' | 'available' | 'downloaded' | 'downloading' | 'error' | string

export interface ModelEntry {
  id: string
  name: string
  size: string
  sizeGb: number
  vramRequired: number
  contextLength: number
  specialty?: string
  description?: string
  tokensPerSec?: number
  quantization?: string | null
  status: ModelStatus
  fitsVram?: boolean
  fitsCurrentVram?: boolean
}

export interface ModelsResponse {
  models: ModelEntry[]
  gpu: { vramTotal: number, vramUsed: number, vramFree: number }
  currentModel: string | null
}

// ---------- /api/models/download-status ----------------------------------

export type DownloadStatus =
  | 'idle'
  | 'downloading'
  | 'verifying'
  | 'complete'
  | 'failed'
  | 'error'
  | 'cancelled'

export interface DownloadProgressRaw {
  status: DownloadStatus
  model?: string
  bytesDownloaded?: number
  bytesTotal?: number
  speedBytesPerSec?: number
  eta?: number | string
  startedAt?: string
  error?: string
  message?: string
}

export interface DownloadProgressView {
  model?: string
  status: DownloadStatus
  percent: number
  bytesDownloaded: number
  bytesTotal: number
  speedMbps: number
  eta?: number | string
  startedAt?: string
  error?: string
}

