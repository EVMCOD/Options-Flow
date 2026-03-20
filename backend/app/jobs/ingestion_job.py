"""
Ingestion job: tenant-aware pipeline orchestration.

The scheduled entry point (run_all_tenants_job) iterates all active tenants,
resolves each tenant's configured data provider, and runs ingestion + signal
for each independently.

For manual/per-tenant execution the run_ingestion_for_tenant function is
called directly (e.g., from the jobs router with an explicit tenant_id).
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.database import AsyncSessionLocal
from app.core.logging_setup import get_logger
from app.providers.registry import ProviderRegistry
from app.services.ingestion import run_ingestion
from app.services.signal import run_signal_engine
from app.tenants.service import (
    get_active_tenants,
    get_active_provider_config,
    mark_provider_healthy,
    mark_provider_error,
)

log = get_logger(__name__)


async def run_ingestion_for_tenant(tenant_id: uuid.UUID) -> None:
    """
    Full pipeline for a single tenant:
      1. Resolve provider from tenant's active TenantProviderConfig
      2. Run ingestion (fetch → raw → normalize)
      3. On success, run signal engine (features → alerts)
    """
    start = time.monotonic()
    log.info("ingestion_job.tenant_started", tenant_id=str(tenant_id))

    async with AsyncSessionLocal() as db:
        try:
            config = await get_active_provider_config(db, tenant_id)
            if config is None:
                log.warning(
                    "ingestion_job.no_provider_config",
                    tenant_id=str(tenant_id),
                )
                return

            provider = ProviderRegistry.resolve(config)
            log.info(
                "ingestion_job.provider_resolved",
                tenant_id=str(tenant_id),
                provider_type=config.provider_type,
                config_id=str(config.id),
            )

            run = await run_ingestion(
                db,
                provider,
                tenant_id=tenant_id,
                provider_config_id=config.id,
                market_data_mode=provider.market_data_mode(),
            )
            elapsed_ingest = time.monotonic() - start
            log.info(
                "ingestion_job.ingestion_complete",
                tenant_id=str(tenant_id),
                run_id=str(run.id),
                provider_type=config.provider_type,
                status=run.status,
                records=run.records_ingested,
                elapsed_s=round(elapsed_ingest, 2),
            )

            if run.status == "success":
                await mark_provider_healthy(db, config)
                signal_summary = await run_signal_engine(
                    db, run_id=run.id, tenant_id=tenant_id
                )
                elapsed_total = time.monotonic() - start
                log.info(
                    "ingestion_job.signals_complete",
                    tenant_id=str(tenant_id),
                    run_id=str(run.id),
                    features=signal_summary.features_created,
                    alerts=signal_summary.alerts_created,
                    passed_prefilters=signal_summary.passed_prefilters,
                    quality_penalized=signal_summary.quality_penalized,
                    insufficient_baseline=signal_summary.insufficient_baseline,
                    elapsed_s=round(elapsed_total, 2),
                )
            else:
                await mark_provider_error(db, config, run.error_message or "ingestion failed")
                log.warning(
                    "ingestion_job.skipping_signals",
                    tenant_id=str(tenant_id),
                    run_id=str(run.id),
                    reason=run.error_message,
                )

        except Exception as exc:
            log.exception(
                "ingestion_job.tenant_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )


async def run_all_tenants_job() -> None:
    """
    Scheduled entry point: iterate all active tenants and run each pipeline.

    Failures for one tenant are isolated — other tenants continue running.
    """
    started_at = datetime.now(tz=timezone.utc)
    log.info("scheduled_job.started", at=started_at.isoformat())

    async with AsyncSessionLocal() as db:
        tenants = await get_active_tenants(db)

    if not tenants:
        log.warning("scheduled_job.no_active_tenants")
        return

    log.info("scheduled_job.tenant_count", count=len(tenants))

    for tenant in tenants:
        try:
            await run_ingestion_for_tenant(tenant.id)
        except Exception as exc:
            # Belt-and-suspenders: run_ingestion_for_tenant already catches internally.
            log.exception(
                "scheduled_job.tenant_unhandled_error",
                tenant_id=str(tenant.id),
                slug=tenant.slug,
                error=str(exc),
            )

    elapsed = (datetime.now(tz=timezone.utc) - started_at).total_seconds()
    log.info("scheduled_job.finished", tenants=len(tenants), elapsed_s=round(elapsed, 2))


# Backward-compat alias: scheduler.py and any external callers can use this name.
run_ingestion_job = run_all_tenants_job
