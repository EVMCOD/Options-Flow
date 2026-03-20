"""
ORM models for hierarchical signal settings.

Two-layer override chain:
  1. tenant_symbol_settings  — per-symbol overrides (highest priority)
  2. tenant_signal_settings  — per-tenant defaults
  3. config.py globals        — fallback for any field not set above

All threshold columns are nullable. Null means "inherit from the next layer."
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TenantSignalSettings(Base):
    """
    Per-tenant signal defaults. One row per tenant (UNIQUE on tenant_id).
    Any field left as None inherits the global default from config.py.
    """
    __tablename__ = "tenant_signal_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    min_premium_proxy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_dte_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_moneyness_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_open_interest: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" — minimum level to fire an alert
    min_alert_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # None = inherit global default (True); False = mute all signals for this tenant
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Cooldown window override (minutes). Null = use global ALERT_COOLDOWN_MINUTES.
    cooldown_window_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TenantSymbolSettings(Base):
    """
    Per-symbol signal overrides. One row per (tenant, symbol).
    Any field left as None inherits from TenantSignalSettings or config.py.
    """
    __tablename__ = "tenant_symbol_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    min_premium_proxy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_dte_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_moneyness_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_open_interest: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_alert_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # None = inherit from tenant/global; False = mute signals for this symbol only
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Cooldown window override (minutes). Null = inherit from tenant/global.
    cooldown_window_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Intelligence layer (007): per-client symbol importance.
    # priority_weight: 0.0–3.0 multiplier applied to priority_score (default 1.0 when null).
    # watchlist_tier: "core" | "secondary" | null — client-facing categorisation.
    priority_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    watchlist_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "symbol", name="uq_tenant_symbol_settings"),
    )
