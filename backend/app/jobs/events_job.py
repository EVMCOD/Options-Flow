"""
Events sync job — scheduled entry point.

Opens its own DB session (independent of any request context) and calls
the event service with all enabled symbols for the default tenant.

Scheduled at 06:00 UTC daily by app/scheduler.py.
Can also be triggered manually via POST /api/v1/jobs/sync-events.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging_setup import get_logger
from app.events.service import EventSyncResult, sync_events

log = get_logger(__name__)

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


async def run_events_sync_job(
    tenant_id: Optional[uuid.UUID] = None,
    symbols: Optional[List[str]] = None,
    types: Optional[List[str]] = None,
    provider_names: Optional[List[str]] = None,
) -> List[EventSyncResult]:
    """
    Fetch and persist upcoming events for *symbols* using the registered providers.

    Opens and manages its own AsyncSession so this can be called from both the
    APScheduler context (no request session available) and from background tasks
    triggered by API endpoints.

    Args:
        tenant_id:      Owning tenant.  Defaults to DEFAULT_TENANT_ID.
        symbols:        Symbols to sync.  If None, reads enabled symbols from
                        ScannerUniverse for the tenant.
        types:          Optional event type filter, e.g. ["earnings"].
        provider_names: Optional provider filter, e.g. ["yfinance"].

    Returns:
        List of EventSyncResult (one per provider that ran).
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT

    async with AsyncSessionLocal() as db:
        # ── Resolve symbol list if not provided ───────────────────────────────
        if symbols is None:
            from sqlalchemy import select as sa_select
            from app.models.models import ScannerUniverse

            univ_q = await db.execute(
                sa_select(ScannerUniverse.symbol)
                .where(ScannerUniverse.tenant_id == effective_tenant)
                .where(ScannerUniverse.enabled.is_(True))
            )
            symbols = [row[0] for row in univ_q.all()]

        if not symbols:
            log.warning(
                "events_job.no_symbols",
                tenant_id=str(effective_tenant),
            )
            return []

        log.info(
            "events_job.start",
            tenant_id=str(effective_tenant),
            symbol_count=len(symbols),
            types=types,
            providers=provider_names,
        )

        try:
            results = await sync_events(
                db=db,
                symbols=symbols,
                tenant_id=effective_tenant,
                types=types,
                provider_names=provider_names,
            )
        except Exception as exc:
            log.exception("events_job.unhandled_error", error=str(exc))
            return []

        total_created = sum(r.created for r in results)
        total_updated = sum(r.updated for r in results)
        total_skipped = sum(r.skipped for r in results)
        total_failed = sum(r.failed for r in results)
        total_errors = sum(len(r.errors) for r in results)

        log.info(
            "events_job.complete",
            providers_run=len(results),
            created=total_created,
            updated=total_updated,
            skipped=total_skipped,
            failed=total_failed,
            errors=total_errors,
        )

        return results
