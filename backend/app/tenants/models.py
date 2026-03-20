"""
Tenant and TenantProviderConfig ORM models.

A Tenant represents a client organisation that uses the platform.
Each tenant has their own:
  - scanner universe (symbols to monitor)
  - one or more provider configurations
  - isolated ingestion runs, signals, and alerts

Security note: credentials_json is stored in plaintext for MVP.
Migration path: wrap ProviderCredentials.__init__ with a call to a KMS
decrypt function. No other code changes are required — see providers/credentials.py.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Human-readable display name (e.g., "Acme Capital")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # URL-safe unique identifier used in API paths (e.g., "acme-capital")
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    provider_configs: Mapped[list["TenantProviderConfig"]] = relationship(
        back_populates="tenant", lazy="noload"
    )


# ---------------------------------------------------------------------------
# Provider config status values
# ---------------------------------------------------------------------------
# These are the valid values for TenantProviderConfig.status.
# Kept as module-level constants to avoid magic strings across the codebase.

PROVIDER_STATUS_UNKNOWN = "unknown"    # default — never been tested
PROVIDER_STATUS_HEALTHY = "healthy"    # last fetch succeeded
PROVIDER_STATUS_ERROR = "error"        # last fetch failed


class TenantProviderConfig(Base):
    """
    Configuration for a specific data provider for a tenant.

    A tenant can have multiple provider configs (e.g., mock for testing,
    Polygon for production), but only the one with is_default=True is used
    for scheduled runs.

    Fields
    ------
    credentials_json : provider-specific auth material (write-only via API)
      - mock:     {}
      - polygon:  {"api_key": "xxx"}
      - ibkr:     {"host": "127.0.0.1", "port": 4002, "client_id": 1}
      - tradier:  {"access_token": "xxx", "sandbox": false}

    config_json : non-sensitive operational settings
      - {"request_timeout_s": 30, "rate_limit_rps": 5, "max_concurrent": 2}

    status : runtime health, managed by the ingestion job
      "unknown" | "healthy" | "error"
      (disabled state is expressed by is_active=False, not by status)

    Constraints
    -----------
    - DB partial unique index: only one is_default=True per tenant.
      Enforced at DB level — the service layer sets this via set_default().
    """
    __tablename__ = "tenant_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Maps to a key registered in ProviderRegistry (e.g., "mock", "polygon")
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # --- Admin-controlled flags ---
    # is_active: admin on/off switch. Inactive configs are never used by the scheduler.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # is_default: marks the primary provider for this tenant.
    # Exactly one active config per tenant should have is_default=True.
    # Enforced by DB partial unique index ix_tpc_one_default_per_tenant.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Credentials and settings (never echoed in GET responses) ---
    credentials_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # --- Runtime health (managed by the ingestion job, not by admins) ---
    # "unknown" | "healthy" | "error"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PROVIDER_STATUS_UNKNOWN
    )
    last_healthy_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Truncated error message from the last failed fetch attempt
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="provider_configs")

    __table_args__ = (
        # Enforce: at most one is_default=True per tenant at the DB level.
        # This is a partial unique index — only rows where is_default=true are covered.
        Index(
            "ix_tpc_one_default_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
    )
