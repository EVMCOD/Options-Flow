"""
Hierarchical signal settings resolver.

Resolution order (first non-None wins):
  1. symbol override  (tenant_symbol_settings)
  2. tenant defaults  (tenant_signal_settings)
  3. global defaults  (app.core.config.settings)

Usage:
    eff = await resolve_signal_settings(db, tenant_id, symbol)
    if not eff.enabled:
        continue  # signal muted for this symbol
    if eff.max_dte_days < dte:
        continue  # too far out
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.signals.models import TenantSignalSettings, TenantSymbolSettings

# Alert level ordering for min_alert_level comparisons
ALERT_LEVEL_ORDER: Dict[str, int] = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


@dataclass
class EffectiveSignalSettings:
    """
    Fully resolved signal settings for one (tenant, symbol) pair.
    All fields are non-null — the fallback chain has been applied.
    """
    min_premium_proxy: float
    max_dte_days: int
    max_moneyness_pct: float
    min_open_interest: int
    min_alert_level: str   # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    enabled: bool
    # Intelligence layer: per-symbol importance multiplier (default 1.0).
    # Flows into priority_score; range 0.0–3.0.
    priority_weight: float = 1.0
    # Optional client-facing tier: "core" | "secondary" | None.
    watchlist_tier: Optional[str] = None
    # Cooldown window (minutes) after an alert fires before same-key duplicates
    # are allowed.  Resolved from symbol → tenant → global default.
    cooldown_window_minutes: int = 60
    # Which layer provided each value: "symbol" | "tenant" | "global"
    sources: Dict[str, str] = field(default_factory=dict)

    def alert_level_passes(self, level: str) -> bool:
        """True if `level` meets or exceeds the minimum configured level."""
        return ALERT_LEVEL_ORDER.get(level, 0) >= ALERT_LEVEL_ORDER.get(self.min_alert_level, 0)


async def resolve_signal_settings(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    symbol: str,
) -> EffectiveSignalSettings:
    """
    Resolve the effective signal settings for a (tenant, symbol) pair.

    Queries up to two DB rows (symbol override + tenant defaults), then
    falls back field-by-field to config.py globals. Returns a fully
    populated EffectiveSignalSettings with source attribution.
    """
    sym_row: Optional[TenantSymbolSettings] = None
    ten_row: Optional[TenantSignalSettings] = None

    if tenant_id is not None:
        # Symbol override
        sym_result = await db.execute(
            select(TenantSymbolSettings)
            .where(TenantSymbolSettings.tenant_id == tenant_id)
            .where(TenantSymbolSettings.symbol == symbol.upper())
        )
        sym_row = sym_result.scalar_one_or_none()

        # Tenant defaults
        ten_result = await db.execute(
            select(TenantSignalSettings)
            .where(TenantSignalSettings.tenant_id == tenant_id)
        )
        ten_row = ten_result.scalar_one_or_none()

    sources: Dict[str, str] = {}

    def _pick(sym_val, ten_val, global_val, field_name):
        if sym_val is not None:
            sources[field_name] = "symbol"
            return sym_val
        if ten_val is not None:
            sources[field_name] = "tenant"
            return ten_val
        sources[field_name] = "global"
        return global_val

    # priority_weight is symbol-only: it's a per-client symbol preference,
    # not a tenant-wide threshold. Falls back to 1.0 (neutral weight).
    priority_weight = (sym_row.priority_weight if sym_row and sym_row.priority_weight is not None else 1.0)
    watchlist_tier = (sym_row.watchlist_tier if sym_row else None)

    return EffectiveSignalSettings(
        min_premium_proxy=_pick(
            sym_row.min_premium_proxy if sym_row else None,
            ten_row.min_premium_proxy if ten_row else None,
            settings.MIN_PREMIUM_PROXY,
            "min_premium_proxy",
        ),
        max_dte_days=_pick(
            sym_row.max_dte_days if sym_row else None,
            ten_row.max_dte_days if ten_row else None,
            settings.MAX_DTE_DAYS,
            "max_dte_days",
        ),
        max_moneyness_pct=_pick(
            sym_row.max_moneyness_pct if sym_row else None,
            ten_row.max_moneyness_pct if ten_row else None,
            settings.MAX_MONEYNESS_PCT,
            "max_moneyness_pct",
        ),
        min_open_interest=_pick(
            sym_row.min_open_interest if sym_row else None,
            ten_row.min_open_interest if ten_row else None,
            settings.MIN_OPEN_INTEREST,
            "min_open_interest",
        ),
        min_alert_level=_pick(
            sym_row.min_alert_level if sym_row else None,
            ten_row.min_alert_level if ten_row else None,
            "LOW",   # global default: fire all levels ≥ LOW
            "min_alert_level",
        ),
        enabled=_pick(
            sym_row.enabled if sym_row else None,
            ten_row.enabled if ten_row else None,
            True,    # global default: signals enabled
            "enabled",
        ),
        cooldown_window_minutes=_pick(
            sym_row.cooldown_window_minutes if sym_row else None,
            ten_row.cooldown_window_minutes if ten_row else None,
            settings.ALERT_COOLDOWN_MINUTES,
            "cooldown_window_minutes",
        ),
        priority_weight=priority_weight,
        watchlist_tier=watchlist_tier,
        sources=sources,
    )
