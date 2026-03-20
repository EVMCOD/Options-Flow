// ---------------------------------------------------------------------------
// Generic API response wrapper
// ---------------------------------------------------------------------------

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Scanner Universe
// ---------------------------------------------------------------------------

export interface ScannerUniverseEntry {
  id: string;
  tenant_id: string | null;
  symbol: string;
  enabled: boolean;
  priority: number;
  created_at: string;
}

export interface ScannerUniverseCreate {
  symbol: string;
  enabled?: boolean;
  priority?: number;
}

export interface ScannerUniversePatch {
  enabled?: boolean;
  priority?: number;
}

// ---------------------------------------------------------------------------
// Ingestion Run
// ---------------------------------------------------------------------------

export interface IngestionRunOut {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "failed";
  records_ingested: number;
  error_message: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Normalized Snapshot
// ---------------------------------------------------------------------------

export interface NormalizedSnapshotOut {
  id: string;
  as_of_ts: string;
  underlying_symbol: string;
  expiry: string;
  strike: string;
  option_type: "C" | "P";
  spot_price: string;
  bid: string;
  ask: string;
  last: string;
  volume: number;
  open_interest: number;
  implied_vol: number | null;
  source: string;
  run_id: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Signal Feature
// ---------------------------------------------------------------------------

export interface SignalFeatureOut {
  id: string;
  snapshot_id: string;
  baseline_volume: number;
  volume_ratio: number;
  volume_zscore: number;
  volume_oi_ratio: number | null;
  premium_proxy: number | null;
  iv_change: number | null;
  anomaly_score: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export type AlertLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AlertStatus = "active" | "acknowledged" | "dismissed";

export interface AlertSummary {
  id: string;
  underlying_symbol: string;
  expiry: string;
  strike: string;
  option_type: "C" | "P";
  as_of_ts: string;
  alert_level: AlertLevel;
  anomaly_score: number;
  raw_anomaly_score: number | null;
  quality_confidence: number | null;
  dte_at_alert: number | null;
  title: string;
  priority_score: number | null;
  status: AlertStatus;
  created_at: string;
  // Event catalyst context (009)
  catalyst_context: string | null;
  days_to_event: number | null;
}

export interface AlertOut extends AlertSummary {
  snapshot_id: string;
  quality_flags: string | null;
  explanation: string;
  priority_score: number | null;
  contributing_factors_json: ContributingFactors | null;
  // Full catalyst fields (only on AlertOut, not AlertSummary)
  next_event_type: string | null;
  next_event_date: string | null;
}

// Intelligence types
export interface CatalystFactor {
  event_type: string;
  event_date: string;
  days_to_event: number;
  context: string;
  boost_applied: number;
}

export interface ContributingFactors {
  volume_spike: {
    ratio: number;
    baseline_avg: number;
    current: number;
    zscore: number;
    assessment: string;
  };
  notional: {
    premium_proxy_usd: number;
    assessment: string;
  };
  timing: {
    dte: number;
    assessment: string;
  };
  quality: {
    confidence: number;
    flags: string[];
    data_source: string;
    assessment: string;
  };
  moneyness: {
    spot: number;
    strike: number;
    distance_pct: number;
    label: string;
  };
  iv: { value: number } | null;
  catalyst?: CatalystFactor;
}

export interface RankedAlert extends AlertSummary {
  explanation: string;
  quality_flags: string | null;
  ranked_priority_score: number | null;
  contributing_factors: ContributingFactors | null;
}

export interface PatternMatch {
  pattern_type: "repeated_prints" | "strike_cluster" | "expiry_cluster" | "volume_acceleration";
  symbol: string;
  description: string;
  alert_ids: string[];
  strength: number;
  first_seen_at: string;
  last_seen_at: string;
  metadata: Record<string, unknown>;
}

export interface PatternDetectionOut {
  window_hours: number;
  min_occurrences: number;
  alerts_analysed: number;
  patterns_found: number;
  patterns: PatternMatch[];
  computed_at: string;
}

export interface DominantItem {
  label: string;
  count: number;
  pct: number;
}

export interface SymbolFlowStory {
  symbol: string;
  window_hours: number;
  session_start: string | null;
  session_end: string | null;
  total_alerts: number;
  alert_distribution: Record<AlertLevel, number>;
  call_put_balance: { calls: number; puts: number; call_pct: number };
  total_notional: number;
  avg_priority_score: number;
  dominant_expiries: DominantItem[];
  dominant_strikes: DominantItem[];
  flow_acceleration: "accelerating" | "steady" | "decelerating" | "insufficient_data";
  top_alerts: Array<{
    id: string;
    title: string;
    alert_level: AlertLevel;
    anomaly_score: number;
    priority_score: number | null;
    created_at: string;
  }>;
  narrative: string;
  computed_at: string;
}

export interface FlowStoryListOut {
  window_hours: number;
  symbols_requested: number;
  symbols_with_data: number;
  stories: SymbolFlowStory[];
  computed_at: string;
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export interface SymbolCount {
  symbol: string;
  count: number;
}

export interface AlertsByLevel {
  LOW: number;
  MEDIUM: number;
  HIGH: number;
  CRITICAL: number;
}

export interface MetricsSummary {
  total_alerts: number;
  active_alerts: number;
  top_symbols: SymbolCount[];
  alerts_by_level: AlertsByLevel;
  last_run_at: string | null;
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export interface JobTriggerResponse {
  job_name: string;
  triggered_at: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Alert filter params
// ---------------------------------------------------------------------------

export interface AlertsQueryParams {
  symbol?: string;
  alert_level?: AlertLevel | "";
  status?: AlertStatus | "";
  limit?: number;
  offset?: number;
}

export interface SnapshotsQueryParams {
  symbol?: string;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Signal Settings (hierarchical per-tenant / per-symbol)
// ---------------------------------------------------------------------------

export interface TenantSignalSettings {
  id: string;
  tenant_id: string;
  min_premium_proxy: number | null;
  max_dte_days: number | null;
  max_moneyness_pct: number | null;
  min_open_interest: number | null;
  min_alert_level: AlertLevel | null;
  enabled: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface SymbolSignalSettings {
  id: string;
  tenant_id: string;
  symbol: string;
  min_premium_proxy: number | null;
  max_dte_days: number | null;
  max_moneyness_pct: number | null;
  min_open_interest: number | null;
  min_alert_level: AlertLevel | null;
  enabled: boolean | null;
  priority_weight: number | null;
  watchlist_tier: "core" | "secondary" | null;
  created_at: string;
  updated_at: string;
}

export interface EffectiveSignalSettings {
  min_premium_proxy: number;
  max_dte_days: number;
  max_moneyness_pct: number;
  min_open_interest: number;
  min_alert_level: AlertLevel;
  enabled: boolean;
  priority_weight: number;
  watchlist_tier: "core" | "secondary" | null;
  sources: Record<string, "symbol" | "tenant" | "global">;
}

export interface SignalSettingsInput {
  min_premium_proxy: number | null;
  max_dte_days: number | null;
  max_moneyness_pct: number | null;
  min_open_interest: number | null;
  min_alert_level: AlertLevel | null;
  enabled: boolean | null;
  priority_weight: number | null;
  watchlist_tier: "core" | "secondary" | null;
}

// ---------------------------------------------------------------------------
// Event Catalysts (009)
// ---------------------------------------------------------------------------

export type EventType =
  | "earnings"
  | "fda_decision"
  | "pdufa"
  | "regulatory"
  | "investor_day"
  | "product_event"
  | "macro_relevant"
  | "custom";

export interface SymbolEventOut {
  id: string;
  tenant_id: string | null;
  symbol: string;
  event_type: EventType | string;
  title: string;
  event_date: string; // ISO date "YYYY-MM-DD"
  event_time: string | null; // "AMC" | "BMO" | "intraday" | "HH:MM"
  source: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface SymbolEventCreate {
  symbol: string;
  event_type: EventType | string;
  title: string;
  event_date: string; // ISO date
  event_time?: string | null;
  source?: string | null;
  notes?: string | null;
}

export interface SymbolEventPatch {
  event_type?: string;
  title?: string;
  event_date?: string;
  event_time?: string | null;
  source?: string | null;
  notes?: string | null;
}

export interface UpcomingEventSummary {
  symbol: string;
  event_type: string;
  title: string;
  event_date: string;
  days_to_event: number;
  catalyst_context: string; // "Earnings in 3 days"
  is_near: boolean;
}
