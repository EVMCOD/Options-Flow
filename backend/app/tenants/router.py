"""
Tenant management API.

Endpoints for administering tenants and their provider configurations.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.schemas import ApiResponse
from app.tenants import service
from app.tenants.schemas import (
    TenantCreate,
    TenantOut,
    TenantPatch,
    TenantProviderConfigCreate,
    TenantProviderConfigOut,
    TenantProviderConfigPatch,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


# ---------------------------------------------------------------------------
# Tenant endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=ApiResponse[List[TenantOut]])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    tenants = await service.get_all_tenants(db)
    return ApiResponse.ok([TenantOut.model_validate(t) for t in tenants])


@router.post("", response_model=ApiResponse[TenantOut], status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    existing = await service.get_tenant_by_slug(db, body.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Tenant slug '{body.slug}' already exists")
    tenant = await service.create_tenant(db, name=body.name, slug=body.slug)
    return ApiResponse.ok(TenantOut.model_validate(tenant))


@router.get("/{tenant_id}", response_model=ApiResponse[TenantOut])
async def get_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await service.get_tenant_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return ApiResponse.ok(TenantOut.model_validate(tenant))


@router.patch("/{tenant_id}", response_model=ApiResponse[TenantOut])
async def patch_tenant(
    tenant_id: uuid.UUID, body: TenantPatch, db: AsyncSession = Depends(get_db)
):
    tenant = await service.get_tenant_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant = await service.patch_tenant(db, tenant, name=body.name, is_active=body.is_active)
    return ApiResponse.ok(TenantOut.model_validate(tenant))


# ---------------------------------------------------------------------------
# Provider config endpoints (nested under /tenants/{id}/providers)
# ---------------------------------------------------------------------------

@router.get("/{tenant_id}/providers", response_model=ApiResponse[List[TenantProviderConfigOut]])
async def list_provider_configs(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await service.get_tenant_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    configs = await service.get_provider_configs(db, tenant_id)
    return ApiResponse.ok([TenantProviderConfigOut.model_validate(c) for c in configs])


@router.post(
    "/{tenant_id}/providers",
    response_model=ApiResponse[TenantProviderConfigOut],
    status_code=201,
)
async def create_provider_config(
    tenant_id: uuid.UUID,
    body: TenantProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    from app.providers.registry import ProviderRegistry

    tenant = await service.get_tenant_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not ProviderRegistry.is_registered(body.provider_type):
        registered = ProviderRegistry.registered_types()
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider_type '{body.provider_type}'. Registered: {registered}",
        )
    cfg = await service.create_provider_config(
        db,
        tenant_id=tenant_id,
        provider_type=body.provider_type,
        credentials_json=body.credentials_json,
        config_json=body.config_json,
    )
    return ApiResponse.ok(TenantProviderConfigOut.model_validate(cfg))


@router.patch(
    "/{tenant_id}/providers/{config_id}",
    response_model=ApiResponse[TenantProviderConfigOut],
)
async def patch_provider_config(
    tenant_id: uuid.UUID,
    config_id: uuid.UUID,
    body: TenantProviderConfigPatch,
    db: AsyncSession = Depends(get_db),
):
    cfg = await service.get_provider_config_by_id(db, config_id)
    if cfg is None or cfg.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Provider config not found")
    cfg = await service.patch_provider_config(
        db,
        cfg,
        is_active=body.is_active,
        credentials_json=body.credentials_json,
        config_json=body.config_json,
    )
    return ApiResponse.ok(TenantProviderConfigOut.model_validate(cfg))


@router.post(
    "/{tenant_id}/providers/{config_id}/set-default",
    response_model=ApiResponse[TenantProviderConfigOut],
)
async def set_default_provider_config(
    tenant_id: uuid.UUID,
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark this config as the default for the tenant's scheduled ingestion runs."""
    tenant = await service.get_tenant_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        cfg = await service.set_default_provider_config(db, tenant_id, config_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ApiResponse.ok(TenantProviderConfigOut.model_validate(cfg))


@router.post(
    "/{tenant_id}/providers/{config_id}/enable",
    response_model=ApiResponse[TenantProviderConfigOut],
)
async def enable_provider_config(
    tenant_id: uuid.UUID,
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    cfg = await service.get_provider_config_by_id(db, config_id)
    if cfg is None or cfg.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Provider config not found")
    cfg = await service.enable_provider_config(db, cfg)
    return ApiResponse.ok(TenantProviderConfigOut.model_validate(cfg))


@router.post(
    "/{tenant_id}/providers/{config_id}/disable",
    response_model=ApiResponse[TenantProviderConfigOut],
)
async def disable_provider_config(
    tenant_id: uuid.UUID,
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    cfg = await service.get_provider_config_by_id(db, config_id)
    if cfg is None or cfg.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Provider config not found")
    cfg = await service.disable_provider_config(db, cfg)
    return ApiResponse.ok(TenantProviderConfigOut.model_validate(cfg))


@router.get(
    "/{tenant_id}/providers/health",
    response_model=ApiResponse[List[TenantProviderConfigOut]],
)
async def get_provider_health(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Return all provider configs for the tenant with their current health status."""
    tenant = await service.get_tenant_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    configs = await service.get_provider_configs(db, tenant_id)
    return ApiResponse.ok([TenantProviderConfigOut.model_validate(c) for c in configs])
