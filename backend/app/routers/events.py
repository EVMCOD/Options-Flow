"""
CRUD router for symbol event catalysts.

Endpoints
─────────
POST   /events                   Create an event
POST   /events/bulk              Create multiple events at once (skips exact duplicates)
GET    /events                   List events (filterable)
GET    /events/upcoming          Next event per symbol in the scanner universe
GET    /events/{event_id}        Get a single event
PATCH  /events/{event_id}        Update an event
DELETE /events/{event_id}        Delete an event
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Alert, ScannerUniverse, SymbolEvent
from app.schemas.schemas import (
    ApiResponse,
    SymbolEventCreate,
    SymbolEventOut,
    SymbolEventPatch,
    UpcomingEventSummary,
)
from app.services.events import resolve_event_context

router = APIRouter(prefix="/events", tags=["events"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


def _effective_tenant(tenant_id: Optional[uuid.UUID]) -> uuid.UUID:
    return tenant_id or _DEFAULT_TENANT


# ── Bulk Create ──────────────────────────────────────────────────────────────

class BulkCreateResult(BaseModel):
    created: int
    skipped: int


@router.post("/bulk", response_model=ApiResponse[BulkCreateResult], status_code=status.HTTP_201_CREATED)
async def bulk_create_events(
    body: List[SymbolEventCreate],
    tenant_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Create multiple events at once. Skips exact duplicates (same symbol + event_date + event_type).
    """
    effective = _effective_tenant(tenant_id)
    created = 0
    skipped = 0

    for item in body:
        sym = item.symbol.upper()
        # Check for existing exact duplicate
        dup_q = await db.execute(
            select(SymbolEvent).where(
                and_(
                    or_(
                        SymbolEvent.tenant_id == effective,
                        SymbolEvent.tenant_id.is_(None),
                    ),
                    SymbolEvent.symbol == sym,
                    SymbolEvent.event_date == item.event_date,
                    SymbolEvent.event_type == item.event_type,
                )
            )
        )
        if dup_q.scalar_one_or_none() is not None:
            skipped += 1
            continue

        event = SymbolEvent(
            tenant_id=effective,
            symbol=sym,
            event_type=item.event_type,
            title=item.title,
            event_date=item.event_date,
            event_time=item.event_time,
            source=item.source,
            notes=item.notes,
        )
        db.add(event)
        created += 1

    await db.commit()
    return ApiResponse.ok(BulkCreateResult(created=created, skipped=skipped))


# ── Create ───────────────────────────────────────────────────────────────────

@router.post("", response_model=ApiResponse[SymbolEventOut], status_code=status.HTTP_201_CREATED)
async def create_event(
    body: SymbolEventCreate,
    tenant_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    effective = _effective_tenant(tenant_id)
    event = SymbolEvent(
        tenant_id=effective,
        symbol=body.symbol.upper(),
        event_type=body.event_type,
        title=body.title,
        event_date=body.event_date,
        event_time=body.event_time,
        source=body.source,
        notes=body.notes,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return ApiResponse.ok(SymbolEventOut.model_validate(event))


# ── List ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=ApiResponse[List[SymbolEventOut]])
async def list_events(
    tenant_id: Optional[uuid.UUID] = Query(None),
    symbol: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    upcoming_only: bool = Query(False, description="Only return events with event_date >= today"),
    days_ahead: Optional[int] = Query(None, description="Return events within N days from today"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    effective = _effective_tenant(tenant_id)
    conditions = [
        or_(
            SymbolEvent.tenant_id == effective,
            SymbolEvent.tenant_id.is_(None),
        )
    ]
    if symbol:
        conditions.append(SymbolEvent.symbol == symbol.upper())
    if event_type:
        conditions.append(SymbolEvent.event_type == event_type)
    if upcoming_only or days_ahead is not None:
        today = date.today()
        conditions.append(SymbolEvent.event_date >= today)
        if days_ahead is not None:
            from datetime import timedelta
            cutoff = today + timedelta(days=days_ahead)
            conditions.append(SymbolEvent.event_date <= cutoff)

    q = (
        select(SymbolEvent)
        .where(and_(*conditions))
        .order_by(SymbolEvent.event_date.asc(), SymbolEvent.symbol.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    events = result.scalars().all()
    return ApiResponse.ok([SymbolEventOut.model_validate(e) for e in events])


# ── Upcoming summary (one per symbol) ────────────────────────────────────────

@router.get("/upcoming", response_model=ApiResponse[List[UpcomingEventSummary]])
async def upcoming_events(
    tenant_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the next upcoming event for each symbol in the scanner universe.
    Useful for a dashboard overview of near-term catalysts.
    """
    effective = _effective_tenant(tenant_id)
    today = date.today()

    # Symbols in the universe for this tenant
    univ_q = await db.execute(
        select(ScannerUniverse.symbol)
        .where(ScannerUniverse.tenant_id == effective)
        .where(ScannerUniverse.enabled.is_(True))
    )
    symbols = [row[0] for row in univ_q.all()]

    results: List[UpcomingEventSummary] = []
    for sym in sorted(set(symbols)):
        ctx = await resolve_event_context(db, sym, effective, today)
        if ctx:
            results.append(
                UpcomingEventSummary(
                    symbol=sym,
                    event_type=ctx.next_event_type,
                    title=ctx.next_event_title,
                    event_date=ctx.next_event_date,
                    days_to_event=ctx.days_to_event,
                    catalyst_context=ctx.catalyst_context,
                    is_near=ctx.is_near,
                )
            )

    results.sort(key=lambda x: x.days_to_event)
    return ApiResponse.ok(results)


# ── Get ──────────────────────────────────────────────────────────────────────

@router.get("/{event_id}", response_model=ApiResponse[SymbolEventOut])
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SymbolEvent).where(SymbolEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return ApiResponse.ok(SymbolEventOut.model_validate(event))


# ── Patch ────────────────────────────────────────────────────────────────────

@router.patch("/{event_id}", response_model=ApiResponse[SymbolEventOut])
async def patch_event(
    event_id: uuid.UUID,
    body: SymbolEventPatch,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SymbolEvent).where(SymbolEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    patch_data = body.model_dump(exclude_unset=True)
    for field, value in patch_data.items():
        setattr(event, field, value)
    event.updated_at = datetime.now(tz=timezone.utc)

    await db.commit()
    await db.refresh(event)
    return ApiResponse.ok(SymbolEventOut.model_validate(event))


# ── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{event_id}", response_model=ApiResponse[None])
async def delete_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SymbolEvent).where(SymbolEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    await db.delete(event)
    await db.commit()
    return ApiResponse.ok(None)


# ── Backfill ──────────────────────────────────────────────────────────────────

@router.post("/backfill-alerts", response_model=ApiResponse[dict])
async def backfill_alert_catalyst(
    tenant_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Retroactively enrich alerts that have NULL catalyst_context.

    Iterates all active alerts (status=active) without catalyst context,
    resolves the current upcoming-event context for each symbol, and writes
    the catalyst fields in-place.

    Note: uses today's date, not the alert's original creation date.
    This means "days_to_event" reflects the current remaining window, not
    the window at alert-fire time.  Only useful for catch-up after seeding
    events for the first time.

    Returns: { updated: int, skipped: int }
    """
    effective = _effective_tenant(tenant_id)
    today = date.today()

    # Load all active alerts with missing catalyst context
    q = (
        select(Alert)
        .where(Alert.tenant_id == effective)
        .where(Alert.status == "active")
        .where(Alert.catalyst_context.is_(None))
    )
    result = await db.execute(q)
    alerts: List[Alert] = list(result.scalars().all())

    # Resolve per-symbol context once (same cache pattern as signal.py)
    event_ctx_cache: dict = {}
    updated = 0
    skipped = 0

    for alert in alerts:
        sym = alert.underlying_symbol
        if sym not in event_ctx_cache:
            event_ctx_cache[sym] = await resolve_event_context(db, sym, effective, today)
        ctx = event_ctx_cache[sym]

        if ctx is None:
            skipped += 1
            continue

        alert.catalyst_context = ctx.catalyst_context
        alert.days_to_event = ctx.days_to_event
        alert.next_event_type = ctx.next_event_type
        alert.next_event_date = ctx.next_event_date
        updated += 1

    if updated > 0:
        await db.commit()

    return ApiResponse.ok({"updated": updated, "skipped": skipped})
