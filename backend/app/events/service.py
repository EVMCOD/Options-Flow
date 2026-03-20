"""
Event sync orchestrator.

Runs registered providers, applies a deterministic conflict policy, and writes
to symbol_events.  The callers (job runner, API endpoint) only need to call
sync_events() — they do not interact with providers or DB directly.

Provider registry
─────────────────
_PROVIDERS is a simple list.  Add a new provider by instantiating it here.
Registration is intentionally explicit (no auto-discovery magic).

Conflict policy
───────────────
For each ProviderEvent returned by a provider, the service checks for existing
DB rows and applies these rules in order:

  1. Exact match  — (tenant_id|NULL, symbol, event_type, event_date)
     → skip.  Re-running is a no-op.

  2. Near-date drift  — same (symbol, event_type), existing row within ±30 days,
     source != "manual".
     → update event_date, source, confidence, notes; preserve event_time.
     Reason: earnings dates shift by a few days; we want one row per earnings
     cycle, not duplicates a week apart.

  3. Near-date drift  — same as above but source == "manual".
     → skip.  Users own manually-entered events; providers do not overwrite them.

  4. No match  → create new row.

Observability
─────────────
Returns List[EventSyncResult], one per provider.  Each has created/updated/
skipped/failed counts and a list of error strings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_setup import get_logger
from app.events.providers.base import BaseEventProvider, ProviderEvent
from app.events.providers.yfinance_earnings import YFinanceEarningsProvider
from app.models.models import SymbolEvent

# ── Provider registry ─────────────────────────────────────────────────────────
# Add new providers here.  They are instantiated once at import time.
# To disable a provider: comment out its entry (do NOT delete it).
_PROVIDERS: List[BaseEventProvider] = [
    YFinanceEarningsProvider(),
    # RegulatoryEventProvider(),  # uncomment when implemented
]

log = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_DRIFT_WINDOW_DAYS = 30   # ±N days for near-date drift detection


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class EventSyncResult:
    """Per-provider sync outcome."""

    provider: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors,
        }


# ── Conflict policy helpers ───────────────────────────────────────────────────

async def _find_exact_match(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    symbol: str,
    event_type: str,
    event_date: date,
) -> Optional[SymbolEvent]:
    """Return the row if an exact (symbol, event_type, event_date) match exists."""
    q = await db.execute(
        select(SymbolEvent).where(
            and_(
                or_(
                    SymbolEvent.tenant_id == tenant_id,
                    SymbolEvent.tenant_id.is_(None),
                ),
                SymbolEvent.symbol == symbol,
                SymbolEvent.event_type == event_type,
                SymbolEvent.event_date == event_date,
            )
        )
    )
    return q.scalar_one_or_none()


async def _find_drift_match(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    symbol: str,
    event_type: str,
    event_date: date,
) -> Optional[SymbolEvent]:
    """
    Return the nearest row within ±DRIFT_WINDOW_DAYS for (symbol, event_type),
    or None if no such row exists.
    """
    lo = event_date - timedelta(days=_DRIFT_WINDOW_DAYS)
    hi = event_date + timedelta(days=_DRIFT_WINDOW_DAYS)
    q = await db.execute(
        select(SymbolEvent)
        .where(
            and_(
                or_(
                    SymbolEvent.tenant_id == tenant_id,
                    SymbolEvent.tenant_id.is_(None),
                ),
                SymbolEvent.symbol == symbol,
                SymbolEvent.event_type == event_type,
                SymbolEvent.event_date >= lo,
                SymbolEvent.event_date <= hi,
            )
        )
        .order_by(func.abs(func.julianday(SymbolEvent.event_date) - func.julianday(str(event_date))))
        .limit(1)
    )
    return q.scalar_one_or_none()


async def _apply_conflict_policy(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    event: ProviderEvent,
    result: EventSyncResult,
) -> None:
    """
    Apply the four-rule conflict policy for a single ProviderEvent.
    Mutates *result* in place.  Does not commit.
    """
    sym = event.symbol.upper()

    # Rule 1 — exact match → skip
    exact = await _find_exact_match(db, tenant_id, sym, event.event_type, event.event_date)
    if exact is not None:
        result.skipped += 1
        log.debug(
            "events_service.exact_match_skip",
            symbol=sym,
            event_type=event.event_type,
            event_date=str(event.event_date),
        )
        return

    # Rule 2 / 3 — near-date drift
    drift = await _find_drift_match(db, tenant_id, sym, event.event_type, event.event_date)
    if drift is not None:
        if drift.source == "manual":
            # Rule 3 — never overwrite manual entries
            result.skipped += 1
            log.debug(
                "events_service.manual_source_skip",
                symbol=sym,
                event_type=event.event_type,
                existing_date=str(drift.event_date),
                provider_date=str(event.event_date),
            )
            return

        # Rule 2 — update drifted row
        drift.event_date = event.event_date
        drift.source = event.source
        drift.notes = event.notes
        # Preserve event_time (user may have set it manually post-creation)
        # Only update if provider has a value and DB is still NULL
        if drift.event_time is None and event.event_time is not None:
            drift.event_time = event.event_time
        result.updated += 1
        log.info(
            "events_service.drift_updated",
            symbol=sym,
            event_type=event.event_type,
            old_date=str(drift.event_date),
            new_date=str(event.event_date),
        )
        return

    # Rule 4 — create new row
    db.add(
        SymbolEvent(
            tenant_id=tenant_id,
            symbol=sym,
            event_type=event.event_type,
            title=event.title,
            event_date=event.event_date,
            event_time=event.event_time,
            source=event.source,
            notes=event.notes,
        )
    )
    result.created += 1
    log.info(
        "events_service.created",
        symbol=sym,
        event_type=event.event_type,
        event_date=str(event.event_date),
        source=event.source,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def get_providers(
    types: Optional[List[str]] = None,
    provider_names: Optional[List[str]] = None,
) -> List[BaseEventProvider]:
    """
    Return the subset of registered providers that match the given filters.

    Args:
        types:          If given, only providers whose supported_types overlap.
        provider_names: If given, only providers whose name is in the list.

    Both filters are AND-ed together (a provider must pass all non-None filters).
    """
    providers = list(_PROVIDERS)
    if types:
        type_set = set(types)
        providers = [p for p in providers if type_set & set(p.supported_types)]
    if provider_names:
        name_set = set(provider_names)
        providers = [p for p in providers if p.name in name_set]
    return providers


async def sync_events(
    db: AsyncSession,
    symbols: List[str],
    tenant_id: Optional[uuid.UUID],
    types: Optional[List[str]] = None,
    provider_names: Optional[List[str]] = None,
) -> List[EventSyncResult]:
    """
    Run all matching providers over *symbols* and persist the results.

    Args:
        db:             Async SQLAlchemy session (caller owns the session scope).
        symbols:        Ticker symbols to sync.
        tenant_id:      Owning tenant for new/updated rows.
        types:          Optional filter: only run providers for these event types.
        provider_names: Optional filter: only run these named providers.

    Returns:
        List of EventSyncResult, one per provider that was run.
        An empty list means no matching providers were found.

    Notes:
        · Commits once per provider after all its events are processed.
          A commit failure rolls back that provider's batch and records the error.
        · Providers that raise NotImplementedError are silently skipped (scaffold).
        · Providers that fail fetch() partially still persist what they returned
          before the error — errors are recorded in EventSyncResult.errors.
    """
    providers = get_providers(types=types, provider_names=provider_names)
    if not providers:
        log.warning(
            "events_service.no_providers",
            types=types,
            provider_names=provider_names,
        )
        return []

    results: List[EventSyncResult] = []

    for provider in providers:
        result = EventSyncResult(provider=provider.name)

        # ── Fetch from external source ────────────────────────────────────────
        try:
            fetch_result = await provider.fetch(symbols)
        except NotImplementedError:
            log.info(
                "events_service.provider_not_implemented",
                provider=provider.name,
            )
            continue
        except Exception as exc:
            result.failed += len(symbols)
            result.errors.append(f"fetch failed: {exc}")
            log.exception(
                "events_service.fetch_error",
                provider=provider.name,
                error=str(exc),
            )
            results.append(result)
            continue

        result.errors.extend(fetch_result.errors)

        # ── Apply conflict policy for each event ──────────────────────────────
        for ev in fetch_result.events:
            ev.source = provider.name    # stamp before conflict check
            try:
                await _apply_conflict_policy(db, tenant_id, ev, result)
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"{ev.symbol}: policy error — {exc}")
                log.exception(
                    "events_service.policy_error",
                    provider=provider.name,
                    symbol=ev.symbol,
                    error=str(exc),
                )

        # ── Commit this provider's batch ──────────────────────────────────────
        if result.created + result.updated > 0:
            try:
                await db.commit()
                log.info(
                    "events_service.committed",
                    provider=provider.name,
                    created=result.created,
                    updated=result.updated,
                    skipped=result.skipped,
                    failed=result.failed,
                )
            except Exception as exc:
                await db.rollback()
                result.errors.append(f"commit failed: {exc}")
                result.created = 0
                result.updated = 0
                log.exception(
                    "events_service.commit_failed",
                    provider=provider.name,
                    error=str(exc),
                )
        else:
            log.info(
                "events_service.nothing_new",
                provider=provider.name,
                skipped=result.skipped,
                failed=result.failed,
            )

        results.append(result)

    return results
