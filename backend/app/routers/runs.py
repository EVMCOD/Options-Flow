"""
Ingestion run inspection endpoints.

GET /runs              — list recent runs for a tenant
GET /runs/compare      — side-by-side comparison of recent runs (for threshold tuning)
GET /runs/{run_id}     — enriched run detail with derived counts and signal summary
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Alert, IngestionRun, NormalizedOptionSnapshot, SignalFeature
from app.schemas.schemas import (
    ApiResponse,
    IngestionRunDetail,
    IngestionRunOut,
    RunCompareEntry,
    RunSignalSummary,
)

router = APIRouter(prefix="/runs", tags=["runs"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


@router.get("", response_model=ApiResponse[List[IngestionRunOut]])
async def list_runs(
    tenant_id: Optional[uuid.UUID] = Query(
        None,
        description="Filter by tenant. Defaults to the system default tenant.",
    ),
    status: Optional[str] = Query(
        None,
        description="Filter by run status: running | success | failed",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    List ingestion runs for a tenant, most recent first.

    Use this to review the history of data fetches and quickly spot failures
    or empty runs. Filter by status=failed to find runs that need investigation.
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT

    q = (
        select(IngestionRun)
        .where(IngestionRun.tenant_id == effective_tenant)
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        q = q.where(IngestionRun.status == status)

    result = await db.execute(q)
    runs = list(result.scalars().all())

    return ApiResponse.ok([IngestionRunOut.model_validate(r) for r in runs])


@router.get("/compare", response_model=ApiResponse[List[RunCompareEntry]])
async def compare_runs(
    tenant_id: Optional[uuid.UUID] = Query(
        None,
        description="Tenant to compare. Defaults to the system default tenant.",
    ),
    limit: int = Query(
        5,
        ge=2,
        le=20,
        description="Number of most-recent successful runs to compare.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Side-by-side comparison of recent runs with their signal summaries.

    Returns the last N successful runs in descending order, each with the full
    signal engine breakdown (filter counts, alert distribution, top symbols, etc.).

    Use this to detect regressions or improvements after changing thresholds:
    - Did pass_prefilters increase after relaxing MAX_DTE_DAYS?
    - Did alerts drop after raising MIN_PREMIUM_PROXY?
    - Is quality_penalized stable or growing?

    Only runs where signal_summary_json is populated are meaningful — runs
    before migration 005 will show null signal_summary.
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT

    result = await db.execute(
        select(IngestionRun)
        .where(IngestionRun.tenant_id == effective_tenant)
        .where(IngestionRun.status == "success")
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
    )
    runs = list(result.scalars().all())

    entries = [
        RunCompareEntry(
            id=r.id,
            started_at=r.started_at,
            finished_at=r.finished_at,
            status=r.status,
            provider_type=r.provider_type,
            market_data_mode=r.market_data_mode,
            records_ingested=r.records_ingested,
            signal_summary=RunSignalSummary.from_json(r.signal_summary_json),
        )
        for r in runs
    ]
    return ApiResponse.ok(entries)


@router.get("/{run_id}", response_model=ApiResponse[IngestionRunDetail])
async def get_run_detail(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Enriched view of a single ingestion run.

    Adds computed fields not stored on the run itself:
    - features_count:    signal features generated from this run
    - alerts_count:      alerts raised from this run
    - distinct_symbols:  distinct underlying symbols ingested

    Also includes signal_summary (from IngestionRun.signal_summary_json) with
    the full filter breakdown, alert distribution, and per-symbol stats — the
    primary tool for threshold calibration.
    """
    result = await db.execute(
        select(IngestionRun).where(IngestionRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Ingestion run not found")

    # Features generated from this run (via normalized_option_snapshots)
    features_q = await db.execute(
        select(func.count(SignalFeature.id))
        .join(
            NormalizedOptionSnapshot,
            SignalFeature.snapshot_id == NormalizedOptionSnapshot.id,
        )
        .where(NormalizedOptionSnapshot.run_id == run_id)
    )
    features_count: int = features_q.scalar_one() or 0

    # Alerts raised from this run
    alerts_q = await db.execute(
        select(func.count(Alert.id))
        .join(
            NormalizedOptionSnapshot,
            Alert.snapshot_id == NormalizedOptionSnapshot.id,
        )
        .where(NormalizedOptionSnapshot.run_id == run_id)
    )
    alerts_count: int = alerts_q.scalar_one() or 0

    # Distinct underlying symbols ingested in this run
    symbols_q = await db.execute(
        select(func.count(func.distinct(NormalizedOptionSnapshot.underlying_symbol)))
        .where(NormalizedOptionSnapshot.run_id == run_id)
    )
    distinct_symbols: int = symbols_q.scalar_one() or 0

    detail = IngestionRunDetail(
        id=run.id,
        tenant_id=run.tenant_id,
        provider_config_id=run.provider_config_id,
        provider_type=run.provider_type,
        market_data_mode=run.market_data_mode,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        records_ingested=run.records_ingested,
        error_message=run.error_message,
        created_at=run.created_at,
        features_count=features_count,
        alerts_count=alerts_count,
        distinct_symbols=distinct_symbols,
        signal_summary=RunSignalSummary.from_json(run.signal_summary_json),
    )
    return ApiResponse.ok(detail)
