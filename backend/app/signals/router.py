"""
Signal settings API — hierarchical per-tenant and per-symbol configuration.

GET  /tenants/{tid}/signal-settings                       — tenant defaults
PUT  /tenants/{tid}/signal-settings                       — upsert tenant defaults
GET  /tenants/{tid}/signal-settings/symbols               — list symbol overrides
GET  /tenants/{tid}/signal-settings/symbols/{sym}         — get symbol override
PUT  /tenants/{tid}/signal-settings/symbols/{sym}         — upsert symbol override
DELETE /tenants/{tid}/signal-settings/symbols/{sym}       — delete symbol override
GET  /tenants/{tid}/signal-settings/symbols/{sym}/effective — resolved config with sources
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.schemas import ApiResponse
from app.signals import service
from app.signals.resolver import resolve_signal_settings
from app.signals.schemas import (
    EffectiveSignalSettingsOut,
    SymbolSignalSettingsIn,
    SymbolSignalSettingsOut,
    TenantSignalSettingsIn,
    TenantSignalSettingsOut,
)

router = APIRouter(tags=["signal-settings"])


# ---------------------------------------------------------------------------
# Tenant defaults
# ---------------------------------------------------------------------------

@router.get(
    "/tenants/{tenant_id}/signal-settings",
    response_model=ApiResponse[TenantSignalSettingsOut],
)
async def get_tenant_signal_settings(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Return the tenant's signal defaults.

    If no defaults have been saved yet, returns null in data (not a 404 —
    the tenant simply inherits all global defaults). Use PUT to set them.
    """
    row = await service.get_tenant_signal_settings(db, tenant_id)
    if row is None:
        return ApiResponse.ok(None)
    return ApiResponse.ok(TenantSignalSettingsOut.model_validate(row))


@router.put(
    "/tenants/{tenant_id}/signal-settings",
    response_model=ApiResponse[TenantSignalSettingsOut],
)
async def upsert_tenant_signal_settings(
    tenant_id: uuid.UUID,
    body: TenantSignalSettingsIn,
    db: AsyncSession = Depends(get_db),
):
    """
    Create or fully replace the tenant's signal defaults.

    Send null for any field to "inherit from global defaults" for that field.
    This does not affect existing symbol-level overrides.
    """
    row = await service.upsert_tenant_signal_settings(db, tenant_id, body)
    return ApiResponse.ok(TenantSignalSettingsOut.model_validate(row))


# ---------------------------------------------------------------------------
# Symbol overrides
# ---------------------------------------------------------------------------

@router.get(
    "/tenants/{tenant_id}/signal-settings/symbols",
    response_model=ApiResponse[List[SymbolSignalSettingsOut]],
)
async def list_symbol_settings(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all symbol-level overrides for this tenant, sorted by symbol."""
    rows = await service.list_symbol_settings(db, tenant_id)
    return ApiResponse.ok([SymbolSignalSettingsOut.model_validate(r) for r in rows])


@router.get(
    "/tenants/{tenant_id}/signal-settings/symbols/{symbol}",
    response_model=ApiResponse[SymbolSignalSettingsOut],
)
async def get_symbol_settings(
    tenant_id: uuid.UUID,
    symbol: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the symbol-level override for one symbol.

    Returns null in data if no override exists for this symbol (not a 404).
    Use PUT to create one.
    """
    row = await service.get_symbol_settings(db, tenant_id, symbol)
    if row is None:
        return ApiResponse.ok(None)
    return ApiResponse.ok(SymbolSignalSettingsOut.model_validate(row))


@router.put(
    "/tenants/{tenant_id}/signal-settings/symbols/{symbol}",
    response_model=ApiResponse[SymbolSignalSettingsOut],
)
async def upsert_symbol_settings(
    tenant_id: uuid.UUID,
    symbol: str,
    body: SymbolSignalSettingsIn,
    db: AsyncSession = Depends(get_db),
):
    """
    Create or fully replace the signal override for one symbol.

    Send null for a field to inherit it from the tenant defaults (or global
    defaults if no tenant defaults exist). Send an explicit value to override.
    """
    row = await service.upsert_symbol_settings(db, tenant_id, symbol, body)
    return ApiResponse.ok(SymbolSignalSettingsOut.model_validate(row))


@router.delete(
    "/tenants/{tenant_id}/signal-settings/symbols/{symbol}",
    response_model=ApiResponse[None],
)
async def delete_symbol_settings(
    tenant_id: uuid.UUID,
    symbol: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove the symbol-level override. The symbol will then inherit from
    tenant defaults or global defaults.

    Returns 404 if no override exists for this symbol.
    """
    deleted = await service.delete_symbol_settings(db, tenant_id, symbol)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"No signal override found for symbol '{symbol.upper()}'",
        )
    return ApiResponse.ok(None)


@router.get(
    "/tenants/{tenant_id}/signal-settings/symbols/{symbol}/effective",
    response_model=ApiResponse[EffectiveSignalSettingsOut],
)
async def get_effective_signal_settings(
    tenant_id: uuid.UUID,
    symbol: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return the fully resolved signal settings for this (tenant, symbol) pair.

    Applies the fallback chain (symbol → tenant → global) and returns the
    resolved values along with a `sources` map showing which layer provided
    each field. Useful for verifying that overrides are taking effect.
    """
    eff = await resolve_signal_settings(db, tenant_id, symbol)
    return ApiResponse.ok(
        EffectiveSignalSettingsOut(
            min_premium_proxy=eff.min_premium_proxy,
            max_dte_days=eff.max_dte_days,
            max_moneyness_pct=eff.max_moneyness_pct,
            min_open_interest=eff.min_open_interest,
            min_alert_level=eff.min_alert_level,
            enabled=eff.enabled,
            sources=eff.sources,
        )
    )
