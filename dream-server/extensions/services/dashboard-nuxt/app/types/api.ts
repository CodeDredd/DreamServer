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

// ---------- /api/extensions/* (Extensions, Welle B.5) -------------------

export type ExtensionStatus =
  | 'enabled'
  | 'cli_installed'
  | 'stopped'
  | 'unhealthy'
  | 'disabled'
  | 'not_installed'
  | 'incompatible'
  | 'installing'
  | 'setting_up'
  | 'error'

export type ExtensionSource = 'core' | 'user' | 'library'

export interface ExtensionFeature {
  name: string
  category?: string
  icon?: string
}

export interface ExtensionEnvVar {
  key?: string
  name?: string
  description?: string
  default?: string
  required?: boolean
}

export type DependencyStatus = 'enabled' | 'disabled' | 'not_installed' | 'incompatible' | 'unknown' | string

export interface ExtensionEntry {
  id: string
  name: string
  description?: string
  category?: string
  status: ExtensionStatus
  source: ExtensionSource
  installable?: boolean
  has_data?: boolean
  port?: number
  external_port_default?: number
  health_endpoint?: string
  gpu_backends?: string[]
  features?: ExtensionFeature[]
  env_vars?: ExtensionEnvVar[]
  depends_on?: string[]
  dependents?: string[]
  dependency_status?: Record<string, DependencyStatus>
}

export interface ExtensionsCatalogSummary {
  total?: number
  installed?: number
  enabled?: number
  cli_installed?: number
  stopped?: number
  unhealthy?: number
  disabled?: number
  not_installed?: number
  installing?: number
  error?: number
  incompatible?: number
}

export interface ExtensionsCatalogResponse {
  extensions: ExtensionEntry[]
  summary?: ExtensionsCatalogSummary
  gpu_backend?: string
  agent_available?: boolean
}

export interface ExtensionProgress {
  status: 'idle' | 'installing' | 'setting_up' | 'started' | 'error' | string
  phase_label?: string
  error?: string
  started_at?: string
}

export interface ExtensionMutationResult {
  message?: string
  restart_required?: boolean
  size_gb_freed?: number
  data_info?: { size_gb: number }
  detail?: unknown
}

export interface ExtensionLogsResponse {
  logs: string
}

// ---------- /api/finance-guru/* (Welle C.1a) -----------------------------

export interface FinanceStatus {
  available: boolean
  configured?: boolean
  message?: string
}

export interface FinanceStrategy {
  name: string
  description?: string
  asset_types?: string[]
  enabled: boolean
  last_ts?: string | null
  last_signals?: number
  last_executed?: number
  last_skipped?: number
  max_position_frac?: number
}

export interface FinanceSchedule {
  cron?: string
  tz?: string
}

export interface FinanceHistoryExtent {
  symbols?: number
}

export interface FinanceStrategiesResponse {
  strategies: FinanceStrategy[]
  schedule?: FinanceSchedule
  next_run?: string | null
  history_extent?: FinanceHistoryExtent | null
}

export interface FinanceKpi {
  seeded_eur?: number
  equity_eur?: number
  cash_eur?: number
  holdings_eur?: number
  realised_pnl_eur?: number
  total_pnl_pct?: number
  n_trades?: number
  n_positions?: number
}

export interface FinancePosition {
  symbol: string
  qty: number
  avg_price: number
  mark_price: number
}

export interface FinanceTrade {
  ts: string
  side: 'BUY' | 'SELL' | string
  symbol: string
  qty: number
  price: number
  reason?: string
  pnl_eur?: number | null
}

export interface FinanceLedger {
  kpi?: FinanceKpi
  positions?: FinancePosition[]
  trades?: FinanceTrade[]
  error?: string
}

export interface FinanceDecideResponse {
  queued_for?: string
  detail?: string
}

// ---------- /api/finance-guru/cycles, /equity-history --------------------

export interface FinanceCycleRow {
  id: number
  ts: string
  strategy: string
  trigger: 'scheduler' | 'manual' | 'backtest' | string
  duration_ms: number
  universe: number
  signals: number
  executed: number
  skipped: number
  equity_eur?: number | null
  cash_eur?: number | null
  pnl_pct?: number | null
  status: 'ok' | 'empty' | 'error' | string
  error?: string | null
}

export interface FinanceCycleSummary {
  total: number
  errors: number
  last_24h: number
  last?: {
    ts: string
    status: string
    signals: number
    executed: number
    error?: string | null
  } | null
}

export interface FinanceCyclesResponse {
  summary: FinanceCycleSummary
  next_run?: string | null
  cycles: FinanceCycleRow[]
}

export interface FinanceEquityPoint {
  ts: string
  equity_eur: number
  cash_eur?: number | null
  pnl_pct?: number | null
}

export interface FinanceEquityResponse {
  strategy: string
  since: string
  points: FinanceEquityPoint[]
}

// ---------- /api/finance-guru/enrichment/* -------------------------------

export interface FinanceAssetAnalysis {
  id: number
  ts: string
  symbol: string
  asset_type: 'stock' | 'crypto' | string
  period_start: string
  period_end: string
  summary: string
  keywords: string[]
  drivers: Array<{
    date?: string
    move_pct?: number
    reason?: string
    news_ids?: Array<string | number>
  }>
  news_ids: Array<string | number>
  confidence: number
  contradictions?: string | null
  model: string
}

export interface FinanceCoverageRow {
  symbol: string
  asset_type: string
  last_ts: string
  n: number
  avg_confidence: number
}

export interface FinanceSourceReliability {
  source: string
  reliability: number
  weight: number
  sample_size: number
  methodology: string
  last_evaluated_at: string
  model: string
}

export interface FinanceEnrichmentRun {
  id: number
  ts: string
  workflow: 'asset_behaviour' | 'source_reliability' | string
  target?: string | null
  status: 'ok' | 'error' | 'skipped' | string
  duration_ms: number
  note?: string | null
}

// ---------- Phase C/D/E: Strategy lifecycle + RAG search -----------------

export type FinanceLifecycleStatus = 'proposed' | 'live' | 'retired' | 'archived'
export type FinanceLifecycleKind   = 'builtin' | 'generated'

export interface FinanceLifecycleRow {
  name: string
  kind: FinanceLifecycleKind | string
  status: FinanceLifecycleStatus | string
  parent_id?: number | null
  source_json?: string | null
  created_at?: string | null
  live_started_at?: string | null
  retired_at?: string | null
  bt_pnl_pct?: number | null
  bt_n_trades?: number | null
  last_audit_at?: string | null
  last_audit_pnl?: number | null
  last_audit_n?: number | null
  retire_reason?: string | null
  lessons_qid?: string | null
}

export interface FinanceLifecycleResponse {
  count: number
  strategies: FinanceLifecycleRow[]
}

export interface FinanceLeaderboardRow {
  name: string
  kind: string
  status: string
  window_pnl_pct?: number | null
  window_cycles?: number | null
  retire_reason?: string | null
}

export interface FinanceLeaderboardResponse {
  window_days: number
  target_pct: number
  rows: FinanceLeaderboardRow[]
}

export interface FinanceAuditRow {
  id: number
  ts: string
  strategy: string
  transition: 'register' | 'propose' | 'promote' | 'retire' | 'archive' | string
  from_status?: string | null
  to_status?: string | null
  pnl_pct?: number | null
  n_cycles?: number | null
  note?: string | null
  actor?: string | null
}

export interface FinanceAuditsResponse {
  audits: FinanceAuditRow[]
}

export interface FinanceDslCatalog {
  version: number
  signals: Record<string, string>
  ops: string[]
  actions: string[]
  sizing: string[]
  limits: {
    max_rules: number
    max_predicates_per_rule: number
    max_nesting_depth: number
  }
  gate: {
    min_backtest_pct: number
    min_backtest_trades: number
    backtest_days: number
    backtest_step_min: number
    universe_limit: number
    quota_per_window: number
    quota_window_days: number
    quota_used: number
  }
}

// Generic RAG hit shape — concrete payload fields vary per collection.
export interface FinanceRelationHit {
  theme: string
  summary?: string
  mechanism?: string | null
  entities?: string[]
  sectors?: string[]
  symbols?: string[]
  evidence_ids?: Array<string | number>
  confidence?: number
  model?: string | null
  ts?: string
  score?: number
}
export interface FinanceRelationsSearchResponse {
  hits: FinanceRelationHit[]
}

export interface FinanceLessonHit {
  strategy: string
  outcome?: string
  pnl_pct?: number | null
  lesson?: string
  keywords?: string[]
  ts?: string
  score?: number
}
export interface FinanceLessonsSearchResponse {
  hits: FinanceLessonHit[]
}

export interface FinanceAnalysisHit {
  symbol: string
  summary?: string
  keywords?: string[]
  confidence?: number
  ts?: string
  score?: number
}
export interface FinanceAnalysesSearchResponse {
  hits: FinanceAnalysisHit[]
}

// ---------------------------------------------------------------------------
// Lotto Oracle (Phase 4 Welle C.1b). Pendant zu /api/lotto/* —
// dashboard-api proxied lotto-oracle.
// Vier Spielarten: lotto-6aus49, eurojackpot, spiel77, super6.
// ---------------------------------------------------------------------------

export interface LottoSubmissionNotice {
  available?: boolean
  note?: string
}

export interface LottoSchedule {
  cron?: string
  tz?: string
}

export interface LottoStatus {
  available?: boolean
  message?: string
  schedule?: LottoSchedule
  submission_api?: LottoSubmissionNotice | null
}

export interface LottoPool {
  name: string
  pick: number
  high: number
  low: number
}

export type LottoGameKind = 'combinatorial' | 'digit'

export interface LottoGame {
  id: string
  label: string
  kind: LottoGameKind
  digits?: number
  pools?: LottoPool[]
  draw_days?: string[]
  n_draws?: number
  last_in_db?: string | null
}

export interface LottoGamesResponse {
  games: LottoGame[]
}

export interface LottoDraw {
  draw_date?: string
  digits?: string
  // dynamic pool keys (e.g. Hauptzahlen, Eurozahlen) via index
  [poolName: string]: unknown
}

export interface LottoDrawsResponse {
  draws: LottoDraw[]
}

export interface LottoTip {
  strategy: string
  display?: string
  digits?: string
  rationale?: string
  // dynamic pool keys (number arrays per pool)
  [poolName: string]: unknown
}

export interface LottoStrategyMeta {
  edge?: number
  avg_match?: number
  expected_random?: number
  n_trials?: number
  window?: number
  hit_rates?: { k: number, prob: number }[]
}

export interface LottoRecencyLookbackBucket {
  samples?: number
  mean?: number | null
  expected_random?: number
  p_at_least?: { k: number, prob: number }[]
}

export interface LottoRecencyStats {
  kind?: 'combinatorial' | 'positional'
  n_history?: number
  main_pool?: string
  lookbacks?: Record<string, LottoRecencyLookbackBucket>
}

export interface LottoTipRunParams {
  recency_k?: number
  [key: string]: unknown
}

export interface LottoTipsRun {
  generated_at?: string
  based_on_draw?: string
  params?: LottoTipRunParams
  tips?: LottoTip[]
  strategy_meta?: Record<string, LottoStrategyMeta>
  recency_stats?: LottoRecencyStats | null
}

export interface LottoTipsResponse {
  run?: LottoTipsRun | null
}

export interface LottoStrategyDescriptor {
  name: string
  label?: string
  description?: string
}

export interface LottoStrategiesResponse {
  strategies: LottoStrategyDescriptor[]
}

export interface LottoSweetSpotRow {
  k: number
  avg_match?: number | null
  expected_random?: number | null
  edge?: number | null
  n_trials?: number
}

export interface LottoSweetSpotResponse {
  recommended_k?: number | null
  window?: number
  per_k?: LottoSweetSpotRow[]
}

export interface LottoStatsFrequencyRow {
  number?: number
  digit?: number
  count: number
  gap?: number
}

export interface LottoStatsPositional {
  position: number
  frequency: { digit: number, count: number }[]
}

export interface LottoStats {
  n: number
  per_position?: LottoStatsPositional[]
  // dynamic pool keys -> { frequency: LottoStatsFrequencyRow[] }
  [poolName: string]: unknown
}

export interface LottoActionResponse {
  detail?: string
}

// ---------------------------------------------------------------------------
// Optimal-Schein / Custom-Schein / Jackpot-Backtest (Lotto Erweiterung)
// ---------------------------------------------------------------------------
export interface LottoSchenField {
  game?: string
  strategy: string
  strategy_label?: string
  strategy_edge?: number | null
  rationale?: string | null
  display?: string
  digits?: string
  // dynamische Pool-Schluessel (Hauptzahlen, Eurozahlen, Superzahl ...)
  [k: string]: unknown
}

export interface LottoScheinBlock {
  game_id: string
  label?: string
  n_fields: number
  fields: LottoSchenField[]
}

export interface LottoOptimalScheinResponse {
  recency_k: number
  schein: Record<string, LottoScheinBlock>
  next_draws: Record<string, string | null>
}

export interface LottoCustomScheinResponse {
  schein: Record<string, LottoScheinBlock>
}

export interface LottoJackpotTier {
  key: string
  label: string
  count: number
}

export interface LottoJackpotStrategy {
  n_trials: number
  years?: number
  window?: number
  tier_counts: LottoJackpotTier[]
  best_match: {
    main?: number
    bonus?: number
    matches?: number
    draw_date?: string | null
    class?: string
  } | null
}

export interface LottoJackpotBacktestResponse {
  game_id: string
  years: number
  rows: number
  recency_k: number
  history_size: number
  per_strategy: Record<string, LottoJackpotStrategy>
}

// ---------------------------------------------------------------------------
// /api/settings/env (Welle A.5). Pendant zur React-Variante in
// dashboard/src/components/settings/EnvEditor.jsx + Settings.jsx.
// Server liefert Sections, Field-Definitionen und aktuelle Values.
// ---------------------------------------------------------------------------

export type EnvFieldType = 'string' | 'integer' | 'boolean' | string

export interface EnvFieldDef {
  key: string
  label?: string
  description?: string
  type?: EnvFieldType
  required?: boolean
  secret?: boolean
  hasValue?: boolean
  default?: string | number | boolean | null
  enum?: string[]
}

export interface EnvSection {
  id: string
  title: string
  keys: string[]
}

export interface EnvValidationIssue {
  key?: string
  message: string
}

export interface EnvApplyPlan {
  supported: boolean
  status?: 'none' | 'pending' | string
  summary?: string
  services?: string[]
}

export interface EnvEditorPayload {
  path?: string
  agentAvailable?: boolean
  saveHint?: string
  restartHint?: string
  backupPath?: string | null
  fields?: Record<string, EnvFieldDef>
  sections?: EnvSection[]
  values?: Record<string, string>
  issues?: EnvValidationIssue[]
  applyPlan?: EnvApplyPlan | null
}

export interface EnvSaveResponse extends EnvEditorPayload {
  // identical envelope; the PUT /api/settings/env returns a fresh editor.
}

export interface EnvApplyResponse {
  message?: string
  detail?: string
}
