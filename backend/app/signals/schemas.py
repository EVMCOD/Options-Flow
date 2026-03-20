"""
Pydantic schemas for hierarchical signal settings.

Three layers:
  TenantSignalSettingsIn/Out  — tenant-level defaults
  SymbolSignalSettingsIn/Out  — symbol-level overrides
  EffectiveSignalSettingsOut  — fully resolved config with source attribution
"""

import uuid
from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AlertLevelLiteral = Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]]

# ---------------------------------------------------------------------------
# Shared field definitions (all nullable = "inherit from parent layer")
# ---------------------------------------------------------------------------

class SignalSettingsFields(BaseModel):
    """Shared nullable fields for both tenant defaults and symbol overrides."""
    min_premium_proxy: Optional[float] = Field(
        None, ge=0, description="Min notional proxy in USD. None = use parent layer default."
    )
    max_dte_days: Optional[int] = Field(
        None, ge=0, le=730, description="Max days to expiry. None = use parent layer default."
    )
    max_moneyness_pct: Optional[float] = Field(
        None, ge=0, le=1, description="|spot/strike−1| threshold. None = use parent layer default."
    )
    min_open_interest: Optional[int] = Field(
        None, ge=0, description="Min open interest. None = use parent layer default."
    )
    min_alert_level: AlertLevelLiteral = Field(
        None, description="Minimum level to fire an alert. None = use parent layer default."
    )
    enabled: Optional[bool] = Field(
        None, description="False = mute signals. None = inherit from parent layer (default True)."
    )


# ---------------------------------------------------------------------------
# Tenant-level defaults
# ---------------------------------------------------------------------------

class TenantSignalSettingsIn(SignalSettingsFields):
    """Request body for PUT /tenants/{tenant_id}/signal-settings."""
    pass


class TenantSignalSettingsOut(SignalSettingsFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Symbol-level overrides
# ---------------------------------------------------------------------------

class SymbolSignalSettingsIn(SignalSettingsFields):
    """Request body for PUT /tenants/{tenant_id}/signal-settings/symbols/{symbol}."""
    # Intelligence layer: per-symbol client priority.
    priority_weight: Optional[float] = Field(
        None, ge=0.0, le=3.0,
        description="Priority multiplier (0–3). 1.0 = neutral; 2+ = featured. None = 1.0."
    )
    watchlist_tier: Optional[str] = Field(
        None, description="Client-facing tier: 'core' | 'secondary' | null."
    )


class SymbolSignalSettingsOut(SignalSettingsFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    symbol: str
    priority_weight: Optional[float] = None
    watchlist_tier: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Effective (resolved) settings
# ---------------------------------------------------------------------------

class EffectiveSignalSettingsOut(BaseModel):
    """
    Fully resolved signal settings for one (tenant, symbol) pair.
    All fields are non-null (fallback chain has been applied).
    sources shows which layer provided each value.
    """
    min_premium_proxy: float
    max_dte_days: int
    max_moneyness_pct: float
    min_open_interest: int
    min_alert_level: str
    enabled: bool
    priority_weight: float = 1.0
    watchlist_tier: Optional[str] = None
    # field_name → "symbol" | "tenant" | "global"
    sources: Dict[str, str]
