"""
CRUD service for tenant signal settings and symbol overrides.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.signals.models import TenantSignalSettings, TenantSymbolSettings
from app.signals.schemas import SymbolSignalSettingsIn, TenantSignalSettingsIn


# ---------------------------------------------------------------------------
# Tenant defaults
# ---------------------------------------------------------------------------

async def get_tenant_signal_settings(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> Optional[TenantSignalSettings]:
    result = await db.execute(
        select(TenantSignalSettings).where(TenantSignalSettings.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def upsert_tenant_signal_settings(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: TenantSignalSettingsIn,
) -> TenantSignalSettings:
    """Create or fully replace the tenant's signal defaults."""
    row = await get_tenant_signal_settings(db, tenant_id)
    now = datetime.now(timezone.utc)

    if row is None:
        row = TenantSignalSettings(tenant_id=tenant_id)
        db.add(row)

    row.min_premium_proxy = data.min_premium_proxy
    row.max_dte_days = data.max_dte_days
    row.max_moneyness_pct = data.max_moneyness_pct
    row.min_open_interest = data.min_open_interest
    row.min_alert_level = data.min_alert_level
    row.enabled = data.enabled
    row.updated_at = now

    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Symbol overrides
# ---------------------------------------------------------------------------

async def list_symbol_settings(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> List[TenantSymbolSettings]:
    result = await db.execute(
        select(TenantSymbolSettings)
        .where(TenantSymbolSettings.tenant_id == tenant_id)
        .order_by(TenantSymbolSettings.symbol.asc())
    )
    return list(result.scalars().all())


async def get_symbol_settings(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    symbol: str,
) -> Optional[TenantSymbolSettings]:
    result = await db.execute(
        select(TenantSymbolSettings)
        .where(TenantSymbolSettings.tenant_id == tenant_id)
        .where(TenantSymbolSettings.symbol == symbol.upper())
    )
    return result.scalar_one_or_none()


async def upsert_symbol_settings(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    symbol: str,
    data: SymbolSignalSettingsIn,
) -> TenantSymbolSettings:
    """Create or fully replace the symbol override for this tenant."""
    sym = symbol.upper()
    row = await get_symbol_settings(db, tenant_id, sym)
    now = datetime.now(timezone.utc)

    if row is None:
        row = TenantSymbolSettings(tenant_id=tenant_id, symbol=sym)
        db.add(row)

    row.min_premium_proxy = data.min_premium_proxy
    row.max_dte_days = data.max_dte_days
    row.max_moneyness_pct = data.max_moneyness_pct
    row.min_open_interest = data.min_open_interest
    row.min_alert_level = data.min_alert_level
    row.enabled = data.enabled
    row.priority_weight = data.priority_weight
    row.watchlist_tier = data.watchlist_tier
    row.updated_at = now

    await db.commit()
    await db.refresh(row)
    return row


async def delete_symbol_settings(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    symbol: str,
) -> bool:
    """Delete symbol override. Returns True if it existed, False if not found."""
    row = await get_symbol_settings(db, tenant_id, symbol)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
