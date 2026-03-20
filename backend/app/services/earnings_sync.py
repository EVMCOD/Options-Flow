"""
Earnings calendar sync via Yahoo Finance (yfinance).

Fetches the next upcoming earnings date for each symbol and upserts it into
symbol_events.  Designed to run nightly as a background job.

Design decisions
────────────────
· Source: yfinance (ticker.calendar["Earnings Date"]) — zero-config, no API key.
  Fallback: ticker.earnings_dates DataFrame if calendar is unavailable.
· Upsert key: (tenant_id, symbol, event_date, event_type="earnings")
  — one row per earnings date per symbol.  Re-running is safe (idempotent).
· Only upcoming dates (>= today) are inserted.
· event_time is intentionally left NULL — yfinance does not reliably expose
  BMO/AMC timing.  Users can update it manually via PATCH /events/{id}.

Required: yfinance >= 0.2.38
  pip install yfinance
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_setup import get_logger
from app.models.models import SymbolEvent

log = get_logger(__name__)


# ── Result dataclass ─────────────────────────────────────────────────────────

class SyncResult:
    """Summary of one sync run."""
    __slots__ = ("synced", "skipped", "errors")

    def __init__(self) -> None:
        self.synced = 0
        self.skipped = 0
        self.errors: List[str] = []

    def to_dict(self) -> dict:
        return {
            "synced": self.synced,
            "skipped": self.skipped,
            "errors": self.errors,
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check_yfinance() -> None:
    try:
        import yfinance  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "yfinance is not installed. "
            "Run: pip install yfinance>=0.2.38"
        )


def _get_next_earnings_date(symbol: str, today: date) -> Optional[date]:
    """
    Return the next upcoming earnings date for *symbol* using yfinance.
    Returns None if yfinance cannot determine an upcoming date.

    Strategy:
      1. ticker.calendar["Earnings Date"] — gives the announced date window.
         Yahoo returns a 1–2 element list; we take the earliest future date.
      2. Fallback: ticker.earnings_dates DataFrame — sorted descending;
         we filter to rows with index > now and take the earliest.
    """
    import yfinance as yf

    try:
        ticker = yf.Ticker(symbol)

        # ── Method 1: calendar (most reliable for near-term dates) ────────────
        try:
            cal = ticker.calendar
            if cal is not None:
                raw = cal.get("Earnings Date")
                if raw is not None:
                    # Normalise to iterable of timestamps/dates
                    items = raw if hasattr(raw, "__iter__") and not isinstance(raw, str) else [raw]
                    candidates: List[date] = []
                    for item in items:
                        try:
                            d = item.date() if hasattr(item, "date") else item
                            if isinstance(d, date) and d >= today:
                                candidates.append(d)
                        except Exception:
                            continue
                    if candidates:
                        return min(candidates)
        except Exception as exc:
            log.debug("earnings_sync.calendar_failed", symbol=symbol, error=str(exc))

        # ── Method 2: earnings_dates DataFrame fallback ───────────────────────
        try:
            import pandas as pd

            df = ticker.earnings_dates
            if df is not None and not df.empty:
                cutoff = pd.Timestamp.now(tz="UTC")
                future = df[df.index > cutoff]
                if not future.empty:
                    return future.sort_index().index[0].date()
        except Exception as exc:
            log.debug("earnings_sync.earnings_dates_failed", symbol=symbol, error=str(exc))

    except Exception as exc:
        log.warning("earnings_sync.ticker_error", symbol=symbol, error=str(exc))

    return None


# ── Public API ────────────────────────────────────────────────────────────────

async def sync_earnings(
    db: AsyncSession,
    symbols: List[str],
    tenant_id: Optional[uuid.UUID],
) -> SyncResult:
    """
    Fetch upcoming earnings for *symbols* from Yahoo Finance and upsert into
    symbol_events.

    Upsert logic: if a row already exists for (tenant_id, symbol, event_date,
    event_type="earnings"), skip it.  Does not update existing rows — so
    manual edits (e.g. setting event_time=AMC) are preserved.

    Commits once at the end.  Rolls back if commit fails.

    Args:
        db:        Async SQLAlchemy session.
        symbols:   List of ticker symbols to sync.
        tenant_id: Tenant that owns these events.  Pass DEFAULT_TENANT_ID for
                   the standard single-tenant setup.

    Returns:
        SyncResult with synced/skipped/errors counts.
    """
    _check_yfinance()

    result = SyncResult()
    today = datetime.now(timezone.utc).date()

    for raw_sym in symbols:
        sym = raw_sym.strip().upper()
        if not sym:
            continue

        try:
            earnings_date = _get_next_earnings_date(sym, today)
        except Exception as exc:
            msg = f"{sym}: unexpected error — {exc}"
            result.errors.append(msg)
            log.warning("earnings_sync.unexpected_error", symbol=sym, error=str(exc))
            continue

        if earnings_date is None:
            log.debug("earnings_sync.no_upcoming", symbol=sym)
            continue

        # ── Upsert check ──────────────────────────────────────────────────────
        # Look for a matching row under this tenant OR globally (tenant_id=NULL).
        # This prevents creating a tenant-scoped duplicate of a global event.
        existing_q = await db.execute(
            select(SymbolEvent).where(
                and_(
                    or_(
                        SymbolEvent.tenant_id == tenant_id,
                        SymbolEvent.tenant_id.is_(None),
                    ),
                    SymbolEvent.symbol == sym,
                    SymbolEvent.event_date == earnings_date,
                    SymbolEvent.event_type == "earnings",
                )
            )
        )
        if existing_q.scalar_one_or_none() is not None:
            result.skipped += 1
            log.debug(
                "earnings_sync.skipped_exists",
                symbol=sym,
                event_date=str(earnings_date),
            )
            continue

        event = SymbolEvent(
            tenant_id=tenant_id,
            symbol=sym,
            event_type="earnings",
            title=f"{sym} Earnings",
            event_date=earnings_date,
            event_time=None,  # not reliably available from yfinance
            source="yfinance",
            notes="Auto-synced via Yahoo Finance (yfinance). Set event_time manually if known.",
        )
        db.add(event)
        result.synced += 1
        log.info(
            "earnings_sync.queued",
            symbol=sym,
            event_date=str(earnings_date),
        )

    if result.synced > 0:
        try:
            await db.commit()
            log.info(
                "earnings_sync.committed",
                synced=result.synced,
                skipped=result.skipped,
                errors=len(result.errors),
            )
        except Exception as exc:
            await db.rollback()
            result.errors.append(f"commit failed: {exc}")
            result.synced = 0
            log.exception("earnings_sync.commit_failed", error=str(exc))
    else:
        log.info(
            "earnings_sync.nothing_new",
            skipped=result.skipped,
            errors=len(result.errors),
        )

    return result
