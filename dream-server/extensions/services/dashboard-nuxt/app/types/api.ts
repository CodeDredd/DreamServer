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

export interface CpuInfo {
  percent: number
  temp_c?: number
}

export interface DiskInfo {
  used_gb: number
  total_gb: number
  percent: number
}

export interface InferenceInfo {
  tokensPerSecond?: number
  lifetimeTokens?: number
  loadedModel?: string
  contextSize?: number
}

export interface SystemStatus {
  gpu: GpuSummary | null
  ram?: RamInfo | null
  cpu?: CpuInfo | null
  disk?: DiskInfo | null
  inference?: InferenceInfo | null
  services: ServiceSummary[]
  model?: ModelSummary | null
  bootstrap?: BootstrapStatus | null
  uptime: number
  version?: string
  tier?: string
}

// ---------- /api/features ------------------------------------------------

export interface FeatureRequirements {
  vramGb?: number
  vramOk?: boolean
  vramFits?: boolean
  services?: string[]
  servicesAll?: string[]
  servicesAny?: string[]
  servicesAvailable?: string[]
  servicesMissing?: string[]
  servicesOk?: boolean
}

export type FeatureStatus =
  | 'enabled'
  | 'available'
  | 'services_needed'
  | 'insufficient_vram'
  | 'unknown'
  | string

export interface FeatureItem {
  id: string
  name: string
  description: string
  icon?: string
  category?: string
  status: FeatureStatus
  enabled?: boolean
  priority?: number
  setupTime?: string
  requirements?: FeatureRequirements
}

export interface FeaturesResponse {
  features: FeatureItem[]
}

// ---------- /api/services/resources --------------------------------------

export interface ServiceContainerStats {
  service_id: string
  container_name: string
  cpu_percent: number
  memory_used_mb: number
  memory_limit_mb: number
  memory_percent: number
  pids: number
}

export interface ServiceDiskStats {
  data_gb: number
  path: string
}

export interface ServiceResourceEntry {
  id: string
  name: string
  type: string
  restartable: boolean
  restart_unavailable_reason: string | null
  container: ServiceContainerStats | null
  disk: ServiceDiskStats | null
}

export interface ServiceResourcesResponse {
  services: ServiceResourceEntry[]
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

// ---------- /api/projects/* (Vikunja proxy, Welle B.1) -------------------

export interface VikunjaStatus {
  available: boolean
  configured: boolean
  version?: string
  url?: string
  message?: string
}

export interface VikunjaProject {
  id: number | string
  title: string
  description?: string
}

export interface VikunjaTask {
  id: number | string
  title: string
  description?: string
  done: boolean
}

// ---------- /api/auth/magic-link/* (Invites, Welle B.2) ------------------

export type InviteScope = 'chat' | string

export interface MagicLinkToken {
  token_hash_prefix: string
  target_username: string
  scope: InviteScope
  reusable: boolean
  note?: string | null
  expires_at: string
  redemption_count: number
  last_redeemed_at?: string | null
  revoked_at?: string | null
}

export interface MagicLinkListResponse {
  tokens: MagicLinkToken[]
}

export interface GeneratedMagicLink {
  url: string
  target_username: string
  scope: InviteScope
  reusable: boolean
  expires_at: string
  token_hash_prefix?: string
}

export interface MagicLinkQrResponse {
  data_url: string
}

// ---------- /api/repo-map/* (Welle B.3) ----------------------------------

export interface RepoMapEntry {
  repo: string
  project_id: number | string
  label?: string
  updated_at?: string | null
}

export interface RepoMap {
  default_project_id: number | string | null
  mappings: RepoMapEntry[]
}

export interface RepoMapLookupResponse {
  repo: string
  project_id: number | string | null
  fallback: boolean
}
