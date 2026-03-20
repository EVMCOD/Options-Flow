import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Alert, IngestionRun, ScannerUniverse
from app.schemas.schemas import AlertsByLevel, ApiResponse, MetricsSummary, SymbolCount

router = APIRouter(prefix="/metrics", tags=["metrics"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


@router.get("/summary", response_model=ApiResponse[MetricsSummary])
async def metrics_summary(
    tenant_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    effective_tenant = tenant_id or _DEFAULT_TENANT

    # Total alerts (all time) for this tenant
    total_q = await db.execute(
        select(func.count(Alert.id)).where(Alert.tenant_id == effective_tenant)
    )
    total_alerts: int = total_q.scalar_one() or 0

    # Active HIGH+CRITICAL alerts — the signal count that matters operationally.
    # LOW/MEDIUM are informational; this number reflects actionable flow.
    active_q = await db.execute(
        select(func.count(Alert.id))
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.status == "active")
        .where(Alert.alert_level.in_(["HIGH", "CRITICAL"]))
    )
    active_alerts: int = active_q.scalar_one() or 0

    # Active alerts by level (status == "active" only).
    # Counts only currently-active alerts, not all-time totals.
    level_q = await db.execute(
        select(Alert.alert_level, func.count(Alert.id))
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.status == "active")
        .group_by(Alert.alert_level)
    )
    level_counts = {row[0]: row[1] for row in level_q.all()}
    alerts_by_level = AlertsByLevel(
        LOW=level_counts.get("LOW", 0),
        MEDIUM=level_counts.get("MEDIUM", 0),
        HIGH=level_counts.get("HIGH", 0),
        CRITICAL=level_counts.get("CRITICAL", 0),
    )

    # Top symbols by alert count (last 24h) for this tenant
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    top_q = await db.execute(
        select(Alert.underlying_symbol, func.count(Alert.id).label("cnt"))
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.created_at >= cutoff)
        .where(Alert.status == "active")
        .where(Alert.alert_level.in_(["HIGH", "CRITICAL"]))
        .group_by(Alert.underlying_symbol)
        .order_by(func.count(Alert.id).desc())
        .limit(10)
    )
    top_symbols: List[SymbolCount] = [
        SymbolCount(symbol=row[0], count=row[1]) for row in top_q.all()
    ]

    # Last run timestamp for this tenant
    last_run_q = await db.execute(
        select(IngestionRun.started_at)
        .where(IngestionRun.tenant_id == effective_tenant)
        .where(IngestionRun.status == "success")
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    last_run_at = last_run_q.scalar_one_or_none()

    return ApiResponse.ok(
        MetricsSummary(
            total_alerts=total_alerts,
            active_alerts=active_alerts,
            top_symbols=top_symbols,
            alerts_by_level=alerts_by_level,
            last_run_at=last_run_at,
        )
    )
