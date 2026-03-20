import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.config import settings
from app.core.database import get_db
from app.jobs.ingestion_job import run_ingestion_for_tenant, run_all_tenants_job
from app.jobs.signal_job import run_signal_job
from app.schemas.schemas import ApiResponse, JobTriggerResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["jobs"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


@router.post("/run-ingestion", response_model=ApiResponse[JobTriggerResponse])
async def trigger_ingestion(
    background_tasks: BackgroundTasks,
    tenant_id: Optional[uuid.UUID] = Query(
        None,
        description="Target tenant. Omit to run all active tenants.",
    ),
):
    """
    Manually trigger a full ingestion + signal run.

    - Without tenant_id: runs all active tenants (same as scheduled job).
    - With tenant_id: runs only that tenant's pipeline.
    """
    triggered_at = datetime.now(tz=timezone.utc)

    if tenant_id is not None:
        background_tasks.add_task(run_ingestion_for_tenant, tenant_id)
        job_name = f"ingestion_job[tenant={tenant_id}]"
    else:
        background_tasks.add_task(run_all_tenants_job)
        job_name = "ingestion_job[all_tenants]"

    return ApiResponse.ok(
        JobTriggerResponse(
            job_name=job_name,
            triggered_at=triggered_at,
            status="triggered",
        )
    )


@router.post("/sync-earnings", response_model=ApiResponse[dict])
async def trigger_earnings_sync(
    background_tasks: BackgroundTasks,
    symbols: Optional[str] = Query(
        None,
        description=(
            "Comma-separated list of symbols to sync. "
            "Omit to sync all enabled symbols in the scanner universe."
        ),
    ),
    tenant_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync upcoming earnings dates from Yahoo Finance (yfinance) into symbol_events.

    - Without `symbols`: syncs every enabled symbol in the scanner universe.
    - With `symbols=AAPL,NVDA,TSLA`: syncs only the given symbols.

    Idempotent: existing (symbol, event_date, event_type=earnings) rows are skipped.
    Requires yfinance: pip install yfinance>=0.2.38
    """
    from app.models.models import ScannerUniverse
    from app.services.earnings_sync import sync_earnings
    from sqlalchemy import select as sa_select

    effective_tenant = tenant_id or _DEFAULT_TENANT

    if symbols:
        sym_list: List[str] = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        univ_q = await db.execute(
            sa_select(ScannerUniverse.symbol)
            .where(ScannerUniverse.tenant_id == effective_tenant)
            .where(ScannerUniverse.enabled.is_(True))
        )
        sym_list = [row[0] for row in univ_q.all()]

    if not sym_list:
        return ApiResponse.ok({"synced": 0, "skipped": 0, "errors": ["No symbols to sync"]})

    # Run synchronously in the request (small universe — typically < 30 symbols,
    # each yfinance call is ~0.5 s).  Switch to background_tasks if latency matters.
    try:
        result = await sync_earnings(db, sym_list, effective_tenant)
    except RuntimeError as exc:
        # yfinance not installed
        return ApiResponse.fail(str(exc))

    return ApiResponse.ok(result.to_dict())


@router.post("/sync-events", response_model=ApiResponse[dict])
async def trigger_events_sync(
    symbols: Optional[str] = Query(
        None,
        description=(
            "Comma-separated list of symbols to sync. "
            "Omit to sync all enabled symbols in the scanner universe."
        ),
    ),
    types: Optional[str] = Query(
        None,
        description="Comma-separated event types, e.g. 'earnings'. Omit for all.",
    ),
    providers: Optional[str] = Query(
        None,
        description="Comma-separated provider names, e.g. 'yfinance'. Omit for all.",
    ),
    tenant_id: Optional[uuid.UUID] = Query(None),
):
    """
    Sync upcoming events from registered providers into symbol_events.

    - Without `symbols`: syncs every enabled symbol in the scanner universe.
    - `types=earnings`: only run earnings providers.
    - `providers=yfinance`: only run the yfinance provider.

    Idempotent: conflict policy prevents duplicates (exact match → skip,
    near-date drift → update, manual source → never overwritten).
    Requires yfinance for the default earnings provider: pip install yfinance>=0.2.38
    """
    from app.jobs.events_job import run_events_sync_job

    effective_tenant = tenant_id or _DEFAULT_TENANT

    sym_list: Optional[List[str]] = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    )
    type_list: Optional[List[str]] = (
        [t.strip() for t in types.split(",") if t.strip()] if types else None
    )
    provider_list: Optional[List[str]] = (
        [p.strip() for p in providers.split(",") if p.strip()] if providers else None
    )

    results = await run_events_sync_job(
        tenant_id=effective_tenant,
        symbols=sym_list,
        types=type_list,
        provider_names=provider_list,
    )

    return ApiResponse.ok({
        "providers_run": len(results),
        "results": [r.to_dict() for r in results],
    })


@router.post("/run-signal", response_model=ApiResponse[JobTriggerResponse])
async def trigger_signal(
    background_tasks: BackgroundTasks,
    tenant_id: Optional[uuid.UUID] = Query(
        None,
        description="Target tenant. Omit to use default tenant.",
    ),
):
    """
    Manually trigger the signal engine on the most recent successful run.
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT
    triggered_at = datetime.now(tz=timezone.utc)
    background_tasks.add_task(run_signal_job, effective_tenant)
    return ApiResponse.ok(
        JobTriggerResponse(
            job_name=f"signal_job[tenant={effective_tenant}]",
            triggered_at=triggered_at,
            status="triggered",
        )
    )
