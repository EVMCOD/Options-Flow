"""
Event catalyst resolution service.

Provides per-symbol upcoming-event context consumed by the signal engine
to enrich alerts and boost priority scores near high-impact events.

Boost model
───────────
When an alert fires within EVENT_NEAR_DAYS of an upcoming event, the
priority_score is multiplied by a catalyst_boost factor:

    event_type             boost at 0–1 d  boost at 2–3 d  boost at 4–7 d
    ──────────────────────────────────────────────────────────────────────
    earnings / fda / pdufa      ×1.30           ×1.21           ×1.12
    all other types             ×1.15           ×1.105          ×1.06

Beyond 7 days the boost is 1.0 (no effect).  The boosted score is capped
at 10.0 so it never exceeds the priority scale ceiling.

The boost is cosmetic context, not a gate: it raises relative ranking but
does not create alerts that would not otherwise fire.  Priority gates
(MIN_PRIORITY_SCORE_HIGH / CRITICAL) are evaluated *after* the boost, so
a near-earnings signal with borderline priority may just cross the gate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_setup import get_logger
from app.models.models import SymbolEvent

log = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Look this many days ahead for upcoming events.
EVENT_NEAR_DAYS: int = 7

# Event types that warrant a stronger boost.
_HIGH_IMPACT_TYPES: frozenset[str] = frozenset(
    {"earnings", "fda_decision", "pdufa"}
)

# Human-readable labels for each event_type.
_TYPE_LABELS: dict[str, str] = {
    "earnings": "Earnings",
    "fda_decision": "FDA decision",
    "pdufa": "PDUFA",
    "regulatory": "Regulatory event",
    "investor_day": "Investor day",
    "product_event": "Product event",
    "macro_relevant": "Macro event",
}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class UpcomingEvent:
    event_id: uuid.UUID
    event_type: str
    title: str
    event_date: date
    days_to_event: int


@dataclass
class EventContext:
    """
    Resolved event context for one symbol at a point in time.

    next_* fields describe the nearest upcoming event.
    catalyst_boost is the priority score multiplier (1.0 = no boost).
    is_near is True when the event is within EVENT_NEAR_DAYS.
    upcoming contains up to 5 events ordered by date ascending.
    """

    next_event_type: str
    next_event_title: str
    next_event_date: date
    days_to_event: int
    is_near: bool
    catalyst_context: str       # human-readable: "Earnings in 3 days"
    catalyst_boost: float       # multiplier applied to priority_score
    upcoming: List[UpcomingEvent] = field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_catalyst_context(event_type: str, title: str, days_to: int) -> str:
    label = _TYPE_LABELS.get(event_type, title)
    if days_to == 0:
        return f"{label} today"
    if days_to == 1:
        return f"{label} tomorrow"
    return f"{label} in {days_to} days"


def _compute_catalyst_boost(days_to: int, event_type: str) -> float:
    """
    Returns a priority_score multiplier based on proximity and event type.
    High-impact event types (earnings, FDA) get a stronger boost ceiling.
    """
    base = 1.30 if event_type in _HIGH_IMPACT_TYPES else 1.15
    if days_to <= 1:
        return base
    if days_to <= 3:
        return round(1.0 + (base - 1.0) * 0.70, 4)
    if days_to <= EVENT_NEAR_DAYS:
        return round(1.0 + (base - 1.0) * 0.40, 4)
    return 1.0


# ── Public API ───────────────────────────────────────────────────────────────

async def resolve_event_context(
    db: AsyncSession,
    symbol: str,
    tenant_id: Optional[uuid.UUID],
    today: date,
) -> Optional[EventContext]:
    """
    Return the EventContext for *symbol* relative to *today*, or None if no
    upcoming events are on record.

    Searches for events belonging to *tenant_id* OR global events
    (tenant_id IS NULL) so that a shared event calendar can be maintained
    without duplicating rows per tenant.
    """
    q = (
        select(SymbolEvent)
        .where(
            and_(
                SymbolEvent.symbol == symbol.upper(),
                SymbolEvent.event_date >= today,
                or_(
                    SymbolEvent.tenant_id == tenant_id,
                    SymbolEvent.tenant_id.is_(None),
                ),
            )
        )
        .order_by(SymbolEvent.event_date.asc())
        .limit(5)
    )
    result = await db.execute(q)
    events: List[SymbolEvent] = list(result.scalars().all())

    if not events:
        return None

    nearest = events[0]
    days_to = (nearest.event_date - today).days
    is_near = days_to <= EVENT_NEAR_DAYS

    upcoming = [
        UpcomingEvent(
            event_id=e.id,
            event_type=e.event_type,
            title=e.title,
            event_date=e.event_date,
            days_to_event=(e.event_date - today).days,
        )
        for e in events
    ]

    ctx = EventContext(
        next_event_type=nearest.event_type,
        next_event_title=nearest.title,
        next_event_date=nearest.event_date,
        days_to_event=days_to,
        is_near=is_near,
        catalyst_context=_format_catalyst_context(nearest.event_type, nearest.title, days_to),
        catalyst_boost=_compute_catalyst_boost(days_to, nearest.event_type),
        upcoming=upcoming,
    )

    log.debug(
        "events.resolved",
        symbol=symbol,
        nearest_type=nearest.event_type,
        days_to=days_to,
        is_near=is_near,
        boost=ctx.catalyst_boost,
    )
    return ctx
