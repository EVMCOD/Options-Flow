import type {
  AlertOut,
  AlertSummary,
  AlertsQueryParams,
  ApiResponse,
  EffectiveSignalSettings,
  FlowStoryListOut,
  IngestionRunOut,
  JobTriggerResponse,
  MetricsSummary,
  NormalizedSnapshotOut,
  PatternDetectionOut,
  RankedAlert,
  ScannerUniverseCreate,
  ScannerUniverseEntry,
  ScannerUniversePatch,
  SignalFeatureOut,
  SignalSettingsInput,
  SnapshotsQueryParams,
  SymbolEventCreate,
  SymbolEventOut,
  SymbolEventPatch,
  SymbolFlowStory,
  SymbolSignalSettings,
  TenantSignalSettings,
  UpcomingEventSummary,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_PREFIX = `${BASE_URL}/api/v1`;

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const url = `${API_PREFIX}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }

  const envelope: ApiResponse<T> = await res.json();

  if (!envelope.success) {
    throw new Error(envelope.error ?? "Unknown API error");
  }

  return envelope.data as T;
}

// ---------------------------------------------------------------------------
// Universe
// ---------------------------------------------------------------------------

export async function getUniverse(): Promise<ScannerUniverseEntry[]> {
  return apiFetch<ScannerUniverseEntry[]>("/universe");
}

export async function createUniverseEntry(
  data: ScannerUniverseCreate
): Promise<ScannerUniverseEntry> {
  return apiFetch<ScannerUniverseEntry>("/universe", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function patchUniverseEntry(
  id: string,
  data: ScannerUniversePatch
): Promise<ScannerUniverseEntry> {
  return apiFetch<ScannerUniverseEntry>(`/universe/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteUniverseEntry(id: string): Promise<void> {
  await apiFetch<null>(`/universe/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export async function getAlerts(
  params: AlertsQueryParams = {}
): Promise<AlertSummary[]> {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set("symbol", params.symbol);
  if (params.alert_level) qs.set("alert_level", params.alert_level);
  if (params.status) qs.set("status", params.status);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<AlertSummary[]>(`/alerts${query}`);
}

export async function getAlert(id: string): Promise<AlertOut> {
  return apiFetch<AlertOut>(`/alerts/${id}`);
}

// ---------------------------------------------------------------------------
// Snapshots
// ---------------------------------------------------------------------------

export async function getSnapshots(
  params: SnapshotsQueryParams = {}
): Promise<NormalizedSnapshotOut[]> {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set("symbol", params.symbol);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<NormalizedSnapshotOut[]>(`/snapshots${query}`);
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export async function getMetricsSummary(): Promise<MetricsSummary> {
  return apiFetch<MetricsSummary>("/metrics/summary");
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export async function triggerIngestion(): Promise<JobTriggerResponse> {
  return apiFetch<JobTriggerResponse>("/jobs/run-ingestion", { method: "POST" });
}

export async function triggerSignal(): Promise<JobTriggerResponse> {
  return apiFetch<JobTriggerResponse>("/jobs/run-signal", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Signal Settings
// ---------------------------------------------------------------------------

const TENANT_ID = "00000000-0000-0000-0000-000000000001";

export async function getTenantSignalSettings(): Promise<TenantSignalSettings | null> {
  return apiFetch<TenantSignalSettings | null>(`/tenants/${TENANT_ID}/signal-settings`);
}

export async function putTenantSignalSettings(
  data: SignalSettingsInput
): Promise<TenantSignalSettings> {
  return apiFetch<TenantSignalSettings>(`/tenants/${TENANT_ID}/signal-settings`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function listSymbolSignalSettings(): Promise<SymbolSignalSettings[]> {
  return apiFetch<SymbolSignalSettings[]>(`/tenants/${TENANT_ID}/signal-settings/symbols`);
}

export async function getSymbolSignalSettings(symbol: string): Promise<SymbolSignalSettings | null> {
  return apiFetch<SymbolSignalSettings | null>(
    `/tenants/${TENANT_ID}/signal-settings/symbols/${symbol}`
  );
}

export async function putSymbolSignalSettings(
  symbol: string,
  data: SignalSettingsInput
): Promise<SymbolSignalSettings> {
  return apiFetch<SymbolSignalSettings>(
    `/tenants/${TENANT_ID}/signal-settings/symbols/${symbol}`,
    { method: "PUT", body: JSON.stringify(data) }
  );
}

export async function deleteSymbolSignalSettings(symbol: string): Promise<void> {
  await apiFetch<null>(`/tenants/${TENANT_ID}/signal-settings/symbols/${symbol}`, {
    method: "DELETE",
  });
}

export async function getEffectiveSignalSettings(
  symbol: string
): Promise<EffectiveSignalSettings> {
  return apiFetch<EffectiveSignalSettings>(
    `/tenants/${TENANT_ID}/signal-settings/symbols/${symbol}/effective`
  );
}

// ---------------------------------------------------------------------------
// Intelligence
// ---------------------------------------------------------------------------

export interface RankedAlertsParams {
  symbol?: string;
  alert_level?: string;
  status?: string;
  hours?: number;
  limit?: number;
}

export async function getRankedAlerts(
  params: RankedAlertsParams = {}
): Promise<RankedAlert[]> {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set("symbol", params.symbol);
  if (params.alert_level) qs.set("alert_level", params.alert_level);
  if (params.status) qs.set("status", params.status);
  if (params.hours !== undefined) qs.set("hours", String(params.hours));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<RankedAlert[]>(`/intelligence/alerts-ranked${query}`);
}

export async function getPatterns(params: {
  symbol?: string;
  hours?: number;
  min_occurrences?: number;
} = {}): Promise<PatternDetectionOut> {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set("symbol", params.symbol);
  if (params.hours !== undefined) qs.set("hours", String(params.hours));
  if (params.min_occurrences !== undefined) qs.set("min_occurrences", String(params.min_occurrences));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<PatternDetectionOut>(`/intelligence/patterns${query}`);
}

export async function getSymbolFlowStory(
  symbol: string,
  hours = 8
): Promise<SymbolFlowStory> {
  return apiFetch<SymbolFlowStory>(`/intelligence/flow-story/${symbol}?hours=${hours}`);
}

export async function getFlowStories(params: {
  hours?: number;
  top_n?: number;
} = {}): Promise<FlowStoryListOut> {
  const qs = new URLSearchParams();
  if (params.hours !== undefined) qs.set("hours", String(params.hours));
  if (params.top_n !== undefined) qs.set("top_n", String(params.top_n));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<FlowStoryListOut>(`/intelligence/flow-story${query}`);
}

// ---------------------------------------------------------------------------
// Events / Catalysts
// ---------------------------------------------------------------------------

export async function getUpcomingEvents(): Promise<UpcomingEventSummary[]> {
  return apiFetch<UpcomingEventSummary[]>("/events/upcoming");
}

export async function getEvents(params: {
  symbol?: string;
  event_type?: string;
  upcoming_only?: boolean;
  days_ahead?: number;
  limit?: number;
} = {}): Promise<SymbolEventOut[]> {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set("symbol", params.symbol);
  if (params.event_type) qs.set("event_type", params.event_type);
  if (params.upcoming_only) qs.set("upcoming_only", "true");
  if (params.days_ahead !== undefined) qs.set("days_ahead", String(params.days_ahead));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<SymbolEventOut[]>(`/events${query}`);
}

export async function createEvent(data: SymbolEventCreate): Promise<SymbolEventOut> {
  return apiFetch<SymbolEventOut>("/events", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function patchEvent(
  id: string,
  data: SymbolEventPatch
): Promise<SymbolEventOut> {
  return apiFetch<SymbolEventOut>(`/events/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteEvent(id: string): Promise<void> {
  await apiFetch<null>(`/events/${id}`, { method: "DELETE" });
}

export async function bulkCreateEvents(
  events: SymbolEventCreate[]
): Promise<{ created: number; skipped: number }> {
  return apiFetch<{ created: number; skipped: number }>("/events/bulk", {
    method: "POST",
    body: JSON.stringify(events),
  });
}
