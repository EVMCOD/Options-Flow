"""
Tenant management service.

Handles CRUD for tenants and their provider configurations.
Also owns the default-tenant seeding logic run at app startup.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_setup import get_logger
from app.tenants.models import (
    Tenant,
    TenantProviderConfig,
    PROVIDER_STATUS_HEALTHY,
    PROVIDER_STATUS_ERROR,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------

async def get_all_tenants(db: AsyncSession) -> List[Tenant]:
    result = await db.execute(
        select(Tenant).order_by(Tenant.created_at.asc())
    )
    return list(result.scalars().all())


async def get_active_tenants(db: AsyncSession) -> List[Tenant]:
    result = await db.execute(
        select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
    )
    return list(result.scalars().all())


async def get_tenant_by_id(db: AsyncSession, tenant_id: uuid.UUID) -> Optional[Tenant]:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def get_tenant_by_slug(db: AsyncSession, slug: str) -> Optional[Tenant]:
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def create_tenant(db: AsyncSession, name: str, slug: str) -> Tenant:
    tenant = Tenant(name=name, slug=slug.lower().strip(), is_active=True)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    log.info("tenant.created", tenant_id=str(tenant.id), slug=tenant.slug)
    return tenant


async def patch_tenant(
    db: AsyncSession,
    tenant: Tenant,
    name: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Tenant:
    if name is not None:
        tenant.name = name
    if is_active is not None:
        tenant.is_active = is_active
    await db.commit()
    await db.refresh(tenant)
    return tenant


# ---------------------------------------------------------------------------
# Provider config CRUD
# ---------------------------------------------------------------------------

async def get_provider_configs(
    db: AsyncSession, tenant_id: uuid.UUID
) -> List[TenantProviderConfig]:
    result = await db.execute(
        select(TenantProviderConfig)
        .where(TenantProviderConfig.tenant_id == tenant_id)
        .order_by(TenantProviderConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def get_active_provider_config(
    db: AsyncSession, tenant_id: uuid.UUID
) -> Optional[TenantProviderConfig]:
    """
    Return the active provider config for a tenant.

    Preference order:
      1. The config with is_default=True (if any active one exists)
      2. The most recently created active config (fallback)
    """
    # Try the explicitly-flagged default first
    result = await db.execute(
        select(TenantProviderConfig)
        .where(TenantProviderConfig.tenant_id == tenant_id)
        .where(TenantProviderConfig.is_active == True)
        .where(TenantProviderConfig.is_default == True)
        .limit(1)
    )
    cfg = result.scalar_one_or_none()
    if cfg is not None:
        return cfg

    # Fall back to most recently created active config
    result = await db.execute(
        select(TenantProviderConfig)
        .where(TenantProviderConfig.tenant_id == tenant_id)
        .where(TenantProviderConfig.is_active == True)
        .order_by(TenantProviderConfig.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_provider_config(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    provider_type: str,
    credentials_json: dict,
    config_json: dict,
) -> TenantProviderConfig:
    cfg = TenantProviderConfig(
        tenant_id=tenant_id,
        provider_type=provider_type,
        credentials_json=credentials_json,
        config_json=config_json,
        is_active=True,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    log.info(
        "provider_config.created",
        config_id=str(cfg.id),
        tenant_id=str(tenant_id),
        provider_type=provider_type,
    )
    return cfg


async def patch_provider_config(
    db: AsyncSession,
    cfg: TenantProviderConfig,
    is_active: Optional[bool] = None,
    credentials_json: Optional[dict] = None,
    config_json: Optional[dict] = None,
) -> TenantProviderConfig:
    if is_active is not None:
        cfg.is_active = is_active
    if credentials_json is not None:
        cfg.credentials_json = credentials_json
    if config_json is not None:
        cfg.config_json = config_json
    await db.commit()
    await db.refresh(cfg)
    return cfg


async def get_provider_config_by_id(
    db: AsyncSession, config_id: uuid.UUID
) -> Optional[TenantProviderConfig]:
    result = await db.execute(
        select(TenantProviderConfig).where(TenantProviderConfig.id == config_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Provider config operational actions
# ---------------------------------------------------------------------------

async def set_default_provider_config(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    config_id: uuid.UUID,
) -> TenantProviderConfig:
    """
    Mark config_id as is_default=True for this tenant, clearing any previous default.

    The DB partial unique index (ix_tpc_one_default_per_tenant) enforces at most
    one default per tenant — we clear the old one first within the same transaction.
    """
    # Clear existing default(s) for this tenant
    await db.execute(
        update(TenantProviderConfig)
        .where(TenantProviderConfig.tenant_id == tenant_id)
        .where(TenantProviderConfig.is_default == True)
        .values(is_default=False)
    )

    cfg = await get_provider_config_by_id(db, config_id)
    if cfg is None or cfg.tenant_id != tenant_id:
        raise ValueError(f"Provider config {config_id} not found for tenant {tenant_id}")

    cfg.is_default = True
    await db.commit()
    await db.refresh(cfg)
    log.info(
        "provider_config.set_default",
        config_id=str(config_id),
        tenant_id=str(tenant_id),
        provider_type=cfg.provider_type,
    )
    return cfg


async def enable_provider_config(
    db: AsyncSession, cfg: TenantProviderConfig
) -> TenantProviderConfig:
    cfg.is_active = True
    await db.commit()
    await db.refresh(cfg)
    log.info("provider_config.enabled", config_id=str(cfg.id))
    return cfg


async def disable_provider_config(
    db: AsyncSession, cfg: TenantProviderConfig
) -> TenantProviderConfig:
    cfg.is_active = False
    await db.commit()
    await db.refresh(cfg)
    log.info("provider_config.disabled", config_id=str(cfg.id))
    return cfg


async def mark_provider_healthy(
    db: AsyncSession, cfg: TenantProviderConfig
) -> None:
    """Record a successful fetch on this provider config."""
    cfg.status = PROVIDER_STATUS_HEALTHY
    cfg.last_healthy_at = datetime.now(tz=timezone.utc)
    cfg.last_error = None
    await db.commit()


async def mark_provider_error(
    db: AsyncSession, cfg: TenantProviderConfig, error: str
) -> None:
    """Record a failed fetch on this provider config."""
    cfg.status = PROVIDER_STATUS_ERROR
    cfg.last_error = error[:500]
    await db.commit()


# ---------------------------------------------------------------------------
# Startup seeding
# ---------------------------------------------------------------------------

async def seed_default_tenant(db: AsyncSession) -> Tenant:
    """
    Ensure the default system tenant exists.

    Uses a fixed UUID (settings.DEFAULT_TENANT_ID) so it can be referenced
    predictably in migrations and backfills without a runtime lookup.

    Idempotent — safe to call on every app startup.
    """
    default_id = uuid.UUID(settings.DEFAULT_TENANT_ID)
    result = await db.execute(select(Tenant).where(Tenant.id == default_id))
    tenant = result.scalar_one_or_none()

    if tenant is not None:
        return tenant

    log.info("tenant.seeding_default")
    tenant = Tenant(
        id=default_id,
        name="Default Workspace",
        slug=settings.DEFAULT_TENANT_SLUG,
        is_active=True,
    )
    db.add(tenant)
    await db.flush()

    # Seed the default provider config (mock) for the default tenant
    provider_cfg = TenantProviderConfig(
        tenant_id=default_id,
        provider_type="mock",
        credentials_json={},
        config_json={},
        is_active=True,
        is_default=True,
    )
    db.add(provider_cfg)
    await db.commit()
    await db.refresh(tenant)
    log.info("tenant.default_seeded", tenant_id=str(tenant.id))
    return tenant
