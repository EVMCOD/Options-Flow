import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Alert
from app.schemas.schemas import AlertOut, AlertSummary, ApiResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


@router.get("", response_model=ApiResponse[List[AlertSummary]])
async def list_alerts(
    tenant_id: Optional[uuid.UUID] = Query(None),
    symbol: Optional[str] = Query(None, description="Filter by underlying symbol"),
    alert_level: Optional[str] = Query(None, description="Filter by level: LOW/MEDIUM/HIGH/CRITICAL"),
    status: Optional[str] = Query(None, description="Filter by status: active/acknowledged/dismissed"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    effective_tenant = tenant_id or _DEFAULT_TENANT
    q = (
        select(Alert)
        .where(Alert.tenant_id == effective_tenant)
        .order_by(Alert.created_at.desc())
    )

    if symbol:
        q = q.where(Alert.underlying_symbol == symbol.upper())
    if alert_level:
        q = q.where(Alert.alert_level == alert_level.upper())
    if status:
        q = q.where(Alert.status == status.lower())

    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    alerts = list(result.scalars().all())
    return ApiResponse.ok([AlertSummary.model_validate(a) for a in alerts])


@router.get("/{alert_id}", response_model=ApiResponse[AlertOut])
async def get_alert(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return ApiResponse.ok(AlertOut.model_validate(alert))
