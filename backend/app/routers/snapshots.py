import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import IngestionRun, NormalizedOptionSnapshot
from app.schemas.schemas import ApiResponse, NormalizedSnapshotOut

router = APIRouter(prefix="/snapshots", tags=["snapshots"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


@router.get("", response_model=ApiResponse[List[NormalizedSnapshotOut]])
async def list_snapshots(
    tenant_id: Optional[uuid.UUID] = Query(None),
    symbol: Optional[str] = Query(None, description="Filter by underlying symbol"),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    effective_tenant = tenant_id or _DEFAULT_TENANT

    # Scope snapshots to tenant via run_id join
    q = (
        select(NormalizedOptionSnapshot)
        .join(IngestionRun, NormalizedOptionSnapshot.run_id == IngestionRun.id)
        .where(IngestionRun.tenant_id == effective_tenant)
        .order_by(NormalizedOptionSnapshot.as_of_ts.desc())
    )

    if symbol:
        q = q.where(NormalizedOptionSnapshot.underlying_symbol == symbol.upper())

    q = q.limit(limit)
    result = await db.execute(q)
    snapshots = list(result.scalars().all())
    return ApiResponse.ok([NormalizedSnapshotOut.model_validate(s) for s in snapshots])
