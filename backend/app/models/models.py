import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ScannerUniverse(Base):
    __tablename__ = "scanner_universe"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # tenant_id scopes this entry to a specific client.
    # SET NULL on tenant delete keeps historical data intact.
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Symbol uniqueness is per-tenant, not global.
    __table_args__ = (
        UniqueConstraint("symbol", "tenant_id", name="uq_scanner_universe_symbol_tenant"),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Which tenant triggered this run. SET NULL if tenant is deleted.
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Which provider config was active at the time of this run.
    # Denormalised provider_type avoids a join when reading run history.
    # SET NULL if the config is ever deleted (historical runs are preserved).
    provider_config_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_provider_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # "delayed" | "live" | "mock" — stamped from provider.market_data_mode() at run start
    market_data_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Full signal engine breakdown persisted after signal run completes.
    # See SignalSummary.to_dict() for the exact schema.
    signal_summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    records_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Use lazy="noload" — these collections can be very large and are never
    # accessed via ORM relationship; queries go directly through the session.
    raw_snapshots: Mapped[list["RawOptionSnapshot"]] = relationship(
        back_populates="run", lazy="noload"
    )
    normalized_snapshots: Mapped[list["NormalizedOptionSnapshot"]] = relationship(
        back_populates="run", lazy="noload"
    )


class RawOptionSnapshot(Base):
    __tablename__ = "raw_option_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["IngestionRun"] = relationship(back_populates="raw_snapshots")


class NormalizedOptionSnapshot(Base):
    __tablename__ = "normalized_option_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    as_of_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    expiry: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    option_type: Mapped[str] = mapped_column(String(1), nullable=False)  # 'C' or 'P'
    spot_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    bid: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    ask: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    last: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    open_interest: Mapped[int] = mapped_column(Integer, nullable=False)
    implied_vol: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["IngestionRun"] = relationship(back_populates="normalized_snapshots")
    # Loaded on-demand only — these are accessed via explicit joins in routers, not ORM traversal.
    signal_feature: Mapped[Optional["SignalFeature"]] = relationship(
        back_populates="snapshot", uselist=False, lazy="noload"
    )
    alert: Mapped[Optional["Alert"]] = relationship(
        back_populates="snapshot", uselist=False, lazy="noload"
    )

    __table_args__ = (
        Index("ix_norm_snapshots_ts_symbol", "as_of_ts", "underlying_symbol"),
    )


class SignalFeature(Base):
    __tablename__ = "signal_features"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("normalized_option_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    baseline_volume: Mapped[float] = mapped_column(Float, nullable=False)
    volume_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    volume_zscore: Mapped[float] = mapped_column(Float, nullable=False)
    volume_oi_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    premium_proxy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iv_change: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Quality-adjusted score (stored as anomaly_score for alert level logic).
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Unpenalized score before quality confidence was applied.
    raw_anomaly_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Multiplier applied to raw score: 0.5–1.0 (1.0 = no penalty).
    quality_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    snapshot: Mapped["NormalizedOptionSnapshot"] = relationship(back_populates="signal_feature")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("normalized_option_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised tenant_id for efficient tenant-scoped alert queries
    # without joining through snapshot → run → tenant.
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    underlying_symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    option_type: Mapped[str] = mapped_column(String(1), nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    alert_level: Mapped[str] = mapped_column(String(10), nullable=False)
    # Quality-adjusted anomaly score (used for alert level determination).
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Unpenalized score — useful for understanding impact of quality penalties.
    raw_anomaly_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Quality confidence multiplier (0.5–1.0). 1.0 means no penalty was applied.
    quality_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # JSON-encoded list of quality issue strings, e.g. '["OI unavailable", "wide spread (85%)"]'
    quality_flags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Calendar days to expiry at the time this alert was created.
    dte_at_alert: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    # Intelligence layer (007): intrinsic priority score (0–10, no recency) and
    # machine-readable factor breakdown for actionable explanations.
    priority_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contributing_factors_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # ── Deduplication / cooldown (008) ───────────────────────────────────────
    # Composite key for same-level same-contract dedup:
    #   {tenant_id}:{symbol}:{expiry}:{strike}:{option_type}:{alert_level}[:{pattern}]
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    # How many identical alerts were suppressed while this one was in cooldown.
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Timestamp of the most recent suppressed duplicate (updated in-place).
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # When this alert was created by escalating a lower-level alert for the same
    # contract, this points to that prior alert.
    escalated_from_alert_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alerts.id", ondelete="SET NULL"),
        nullable=True,
    )
    # "escalated" when this alert has been superseded by a higher-level escalation.
    # Null on normal active alerts.
    suppression_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Expiry of the active cooldown window.  Duplicates arriving before this
    # timestamp are suppressed; after it, a fresh alert is allowed.
    cooldown_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Event catalyst context (009) ─────────────────────────────────────────
    # Snapshot of the nearest upcoming event at alert creation time.
    # Stored denormalised so the alert record is self-contained even if the
    # event is later edited or deleted.
    catalyst_context: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    days_to_event: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    next_event_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    next_event_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    snapshot: Mapped["NormalizedOptionSnapshot"] = relationship(back_populates="alert")


class SymbolEvent(Base):
    """
    Upcoming event catalyst for a symbol.

    Scoped to a tenant (for tenant-specific events like proprietary IR calendars)
    or global (tenant_id=NULL) for events visible to all tenants.

    Supported event_type values:
        earnings, fda_decision, pdufa, regulatory,
        investor_day, product_event, macro_relevant, custom
    """

    __tablename__ = "symbol_events"
    __table_args__ = (
        Index("ix_symbol_events_symbol_date", "symbol", "event_date"),
        Index("ix_symbol_events_tenant_symbol_date", "tenant_id", "symbol", "event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL = global event visible to all tenants.
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Optional timing hint: "AMC" (after market close), "BMO" (before market open),
    # "intraday", or a HH:MM string.  NULL = unknown timing.
    event_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
