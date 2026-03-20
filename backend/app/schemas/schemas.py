from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic API response wrapper
# ---------------------------------------------------------------------------

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None

    @classmethod
    def ok(cls, data: T) -> "ApiResponse[T]":
        return cls(success=True, data=data, error=None)

    @classmethod
    def fail(cls, error: str) -> "ApiResponse[None]":
        return cls(success=False, data=None, error=error)


# ---------------------------------------------------------------------------
# Scanner Universe
# ---------------------------------------------------------------------------

class ScannerUniverseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    symbol: str
    enabled: bool
    priority: int
    created_at: datetime


class ScannerUniverseCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    enabled: bool = True
    priority: int = 0


class ScannerUniversePatch(BaseModel):
    enabled: Optional[bool] = None
    priority: Optional[int] = None


# ---------------------------------------------------------------------------
# Ingestion Run
# ---------------------------------------------------------------------------

class IngestionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    provider_config_id: Optional[uuid.UUID]
    provider_type: Optional[str]
    market_data_mode: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    records_ingested: int
    error_message: Optional[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Normalized Option Snapshot
# ---------------------------------------------------------------------------

class NormalizedSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    as_of_ts: datetime
    underlying_symbol: str
    expiry: date
    strike: Decimal
    option_type: str
    spot_price: Decimal
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume: int
    open_interest: int
    implied_vol: Optional[float]
    source: str
    run_id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Signal Feature
# ---------------------------------------------------------------------------

class SignalFeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    baseline_volume: float
    volume_ratio: float
    volume_zscore: float
    volume_oi_ratio: Optional[float]
    premium_proxy: Optional[float]
    iv_change: Optional[float]
    anomaly_score: float
    raw_anomaly_score: Optional[float]
    quality_confidence: Optional[float]
    created_at: datetime


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    underlying_symbol: str
    expiry: date
    strike: Decimal
    option_type: str
    as_of_ts: datetime
    alert_level: str
    anomaly_score: float
    raw_anomaly_score: Optional[float]
    quality_confidence: Optional[float]
    quality_flags: Optional[str]   # JSON-encoded list, e.g. '["OI unavailable"]'
    dte_at_alert: Optional[int]
    title: str
    explanation: str
    # Intelligence layer: intrinsic priority (0–10) and structured factor breakdown
    priority_score: Optional[float] = None
    contributing_factors_json: Optional[dict] = None
    status: str
    created_at: datetime
    # Deduplication / cooldown (008)
    dedupe_key: Optional[str] = None
    duplicate_count: int = 0
    last_seen_at: Optional[datetime] = None
    escalated_from_alert_id: Optional[uuid.UUID] = None
    suppression_reason: Optional[str] = None
    cooldown_expires_at: Optional[datetime] = None
    # Event catalyst context (009)
    catalyst_context: Optional[str] = None
    days_to_event: Optional[int] = None
    next_event_type: Optional[str] = None
    next_event_date: Optional[date] = None


class AlertSummary(BaseModel):
    """Lighter payload for table views — omits explanation body."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    underlying_symbol: str
    expiry: date
    strike: Decimal
    option_type: str
    as_of_ts: datetime
    alert_level: str
    anomaly_score: float
    raw_anomaly_score: Optional[float]
    quality_confidence: Optional[float]
    dte_at_alert: Optional[int]
    title: str
    # Intelligence layer: base priority score for client-side sorting
    priority_score: Optional[float] = None
    status: str
    created_at: datetime
    # Deduplication (008): suppression summary for feed views
    duplicate_count: int = 0
    last_seen_at: Optional[datetime] = None
    escalated_from_alert_id: Optional[uuid.UUID] = None
    # Event catalyst context (009)
    catalyst_context: Optional[str] = None
    days_to_event: Optional[int] = None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class SymbolCount(BaseModel):
    symbol: str
    count: int


class AlertsByLevel(BaseModel):
    LOW: int = 0
    MEDIUM: int = 0
    HIGH: int = 0
    CRITICAL: int = 0


class MetricsSummary(BaseModel):
    total_alerts: int
    active_alerts: int
    top_symbols: List[SymbolCount]
    alerts_by_level: AlertsByLevel
    last_run_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class JobTriggerResponse(BaseModel):
    job_name: str
    triggered_at: datetime
    status: str


# ---------------------------------------------------------------------------
# Ingestion Run — enriched detail view
# ---------------------------------------------------------------------------

class SignalFilterBreakdown(BaseModel):
    """Per-filter counts from one signal engine run."""
    zero_price: int = 0
    far_expiry: int = 0
    deep_otm: int = 0
    low_premium: int = 0
    low_oi: int = 0


class SignalAlertDistribution(BaseModel):
    LOW: int = 0
    MEDIUM: int = 0
    HIGH: int = 0
    CRITICAL: int = 0


class SignalTopSymbol(BaseModel):
    symbol: str
    contracts_evaluated: int
    features: int
    alerts: int


class RunSignalSummary(BaseModel):
    """
    Typed view of IngestionRun.signal_summary_json.
    Provides the full signal engine breakdown for a single run.
    """
    snapshots_above_min_volume: int = 0
    already_processed: int = 0
    filtered: SignalFilterBreakdown = SignalFilterBreakdown()
    passed_prefilters: int = 0
    insufficient_baseline: int = 0
    features_created: int = 0
    quality_penalized: int = 0
    alerts_created: int = 0
    alerts_suppressed: int = 0
    alerts_escalated: int = 0
    snapshots_failed: int = 0
    alert_distribution: SignalAlertDistribution = SignalAlertDistribution()
    avg_anomaly_score: float = 0.0
    top_symbols: List[SignalTopSymbol] = []
    thresholds_applied: dict = {}
    elapsed_ms: int = 0

    @classmethod
    def from_json(cls, data: Optional[dict]) -> Optional["RunSignalSummary"]:
        if data is None:
            return None
        try:
            d = dict(data)
            if "filtered" in d and isinstance(d["filtered"], dict):
                d["filtered"] = SignalFilterBreakdown(**d["filtered"])
            if "alert_distribution" in d and isinstance(d["alert_distribution"], dict):
                d["alert_distribution"] = SignalAlertDistribution(**d["alert_distribution"])
            if "top_symbols" in d:
                d["top_symbols"] = [
                    SignalTopSymbol(**s) if isinstance(s, dict) else s
                    for s in d["top_symbols"]
                ]
            return cls(**d)
        except Exception:
            return None


class IngestionRunDetail(BaseModel):
    """
    Enriched view of a single ingestion run.

    Adds computed fields (features_count, alerts_count, distinct_symbols)
    derived from related tables, plus the full signal engine summary
    persisted by the signal engine after the run completes.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    provider_config_id: Optional[uuid.UUID]
    provider_type: Optional[str]
    market_data_mode: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    records_ingested: int
    error_message: Optional[str]
    created_at: datetime
    # Computed from related tables:
    features_count: int
    alerts_count: int
    distinct_symbols: int
    # Signal engine breakdown (None if signal has not run yet for this run):
    signal_summary: Optional[RunSignalSummary] = None


class RunCompareEntry(BaseModel):
    """Single run entry for the compare endpoint."""
    id: uuid.UUID
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    provider_type: Optional[str]
    market_data_mode: Optional[str]
    records_ingested: int
    signal_summary: Optional[RunSignalSummary] = None


# ---------------------------------------------------------------------------
# Threshold tuning review
# ---------------------------------------------------------------------------

class FilterTuningNote(BaseModel):
    filter_name: str
    setting: str
    current_value: object
    avg_removal_rate: float   # fraction of snapshots_above_min_volume removed
    recommendation: Optional[str]


class ThresholdReview(BaseModel):
    """
    Heuristic analysis of recent runs' filter effectiveness.
    Helps decide whether thresholds need tightening or relaxing.
    """
    runs_analyzed: int
    lookback_runs: int
    filter_notes: List[FilterTuningNote]
    alert_rate_note: Optional[str]
    baseline_note: Optional[str]
    general_notes: List[str]


# ---------------------------------------------------------------------------
# Provider Diagnostics
# ---------------------------------------------------------------------------

class ContractSample(BaseModel):
    """
    Lightweight representation of one option contract from a diagnostic fetch.
    No sensitive data — credentials are never included.
    """
    symbol: str
    expiry: str          # ISO date string, e.g. "2025-06-20"
    strike: float
    option_type: str     # "C" or "P"
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_vol: Optional[float]
    data_flags: List[str]  # e.g. ["no_oi", "no_iv", "est_bid"]


class SymbolDiagnostics(BaseModel):
    """Per-symbol result from a provider test-fetch."""
    symbol: str
    elapsed_ms: int
    status: str                      # "ok" | "empty" | "error"
    empty_reason: Optional[str]      # populated when status=="empty"
    error_detail: Optional[str]      # populated when status=="error"
    contracts_returned: int
    contracts_quality_passed: int    # passed the zero-price quality gate
    missing_volume: int              # contracts with volume == 0
    missing_open_interest: int       # contracts with open_interest == 0
    missing_iv: int                  # contracts with implied_vol is None
    missing_bid: int                 # contracts with bid <= 0.01
    missing_ask: int                 # contracts with ask <= 0.01
    missing_last: int                # contracts with last <= 0.01
    sample_contracts: List[ContractSample]  # up to 3, highest volume first


class ProviderTestReport(BaseModel):
    """
    Full diagnostic report from a provider test-fetch.

    Includes per-symbol breakdown, aggregate quality metrics, and a
    plain-language quality verdict. Credentials are never included —
    only config_json (operational settings) appears in config_effective.
    """
    tested_at: datetime
    elapsed_ms: int
    tenant_id: str
    config_id: str
    provider_type: str
    market_data_mode: str
    config_effective: dict      # config_json only — no credentials_json
    symbols_requested: List[str]
    symbols_with_data: int
    symbols_empty: int
    symbols_errored: int
    total_contracts_returned: int
    total_contracts_quality_passed: int
    avg_contracts_per_symbol: float
    pct_usable_bid_ask: float   # fraction with usable price (passed quality gate)
    pct_usable_volume: float    # fraction with volume > 0
    pct_usable_oi: float        # fraction with open_interest > 0
    pct_usable_iv: float        # fraction with implied_vol populated
    quality_verdict: str        # "poor" | "limited" | "usable" | "good"
    quality_notes: List[str]    # plain-language observations
    per_symbol: List[SymbolDiagnostics]


# ---------------------------------------------------------------------------
# Event Catalysts (009)
# ---------------------------------------------------------------------------

class SymbolEventCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    event_type: str = Field(
        ..., min_length=1, max_length=50,
        description=(
            "earnings | fda_decision | pdufa | regulatory | "
            "investor_day | product_event | macro_relevant | custom"
        ),
    )
    title: str = Field(..., min_length=1, max_length=255)
    event_date: date
    event_time: Optional[str] = Field(
        None, max_length=10,
        description="'AMC', 'BMO', 'intraday', or 'HH:MM'.  Null = unknown.",
    )
    source: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class SymbolEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    symbol: str
    event_type: str
    title: str
    event_date: date
    event_time: Optional[str]
    source: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class SymbolEventPatch(BaseModel):
    event_type: Optional[str] = Field(None, min_length=1, max_length=50)
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    event_date: Optional[date] = None
    event_time: Optional[str] = Field(None, max_length=10)
    source: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class UpcomingEventSummary(BaseModel):
    """Lightweight per-symbol summary used by GET /events/upcoming."""

    symbol: str
    event_type: str
    title: str
    event_date: date
    days_to_event: int
    catalyst_context: str   # e.g. "Earnings in 3 days"
    is_near: bool           # True when days_to_event <= 7
