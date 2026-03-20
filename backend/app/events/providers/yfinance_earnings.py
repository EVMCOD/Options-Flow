"""
Yahoo Finance earnings provider.

Fetches the next upcoming earnings date for each symbol using yfinance.
Migrates and supersedes the logic in app/services/earnings_sync.py.

Strategy
────────
1. ticker.calendar["Earnings Date"] — returns the announced date window.
   Yahoo returns a 1–2 element list; we take the earliest future date.
2. Fallback: ticker.earnings_dates DataFrame — sorted descending;
   filter to rows with index > now, take the earliest.

Notes
─────
· event_time is left None — yfinance does not reliably expose BMO/AMC.
  Users can set it via PATCH /events/{id}.
· confidence=0.8 for calendar source (announced but not always final),
  confidence=0.6 for earnings_dates fallback (estimated from history).
· Requires: pip install yfinance>=0.2.38
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import List, Optional

from app.core.logging_setup import get_logger
from app.events.providers.base import BaseEventProvider, ProviderEvent, ProviderFetchResult

log = get_logger(__name__)


def _require_yfinance() -> None:
    try:
        import yfinance  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "yfinance is not installed. Run: pip install yfinance>=0.2.38"
        )


def _fetch_earnings_date_sync(symbol: str, today: date) -> tuple[Optional[date], float]:
    """
    Return (earnings_date, confidence) for *symbol*, or (None, 0.0).
    Runs synchronously — called via asyncio.to_thread() to avoid blocking
    the event loop during yfinance HTTP calls.
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)

    # ── Method 1: calendar (most reliable) ───────────────────────────────────
    try:
        cal = ticker.calendar
        if cal is not None:
            raw = cal.get("Earnings Date")
            if raw is not None:
                items = (
                    raw
                    if (hasattr(raw, "__iter__") and not isinstance(raw, str))
                    else [raw]
                )
                candidates: List[date] = []
                for item in items:
                    try:
                        d = item.date() if hasattr(item, "date") else item
                        if isinstance(d, date) and d >= today:
                            candidates.append(d)
                    except Exception:
                        continue
                if candidates:
                    return min(candidates), 0.8
    except Exception as exc:
        log.debug("yfinance_earnings.calendar_failed", symbol=symbol, error=str(exc))

    # ── Method 2: earnings_dates DataFrame (historical / estimated) ───────────
    try:
        import pandas as pd

        df = ticker.earnings_dates
        if df is not None and not df.empty:
            cutoff = pd.Timestamp.now(tz="UTC")
            future = df[df.index > cutoff]
            if not future.empty:
                return future.sort_index().index[0].date(), 0.6
    except Exception as exc:
        log.debug(
            "yfinance_earnings.earnings_dates_failed", symbol=symbol, error=str(exc)
        )

    return None, 0.0


class YFinanceEarningsProvider(BaseEventProvider):
    """
    Earnings calendar provider backed by Yahoo Finance (yfinance).

    No API key required.  Rate-limited by Yahoo — do not call in tight loops.
    Safe for nightly batch jobs over a universe of ≤ 100 symbols.
    """

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def supported_types(self) -> List[str]:
        return ["earnings"]

    async def fetch(self, symbols: List[str]) -> ProviderFetchResult:
        _require_yfinance()

        result = ProviderFetchResult()
        today = datetime.now(timezone.utc).date()

        for raw_sym in symbols:
            sym = raw_sym.strip().upper()
            if not sym:
                continue

            try:
                earnings_date, confidence = await asyncio.to_thread(
                    _fetch_earnings_date_sync, sym, today
                )
            except Exception as exc:
                msg = f"{sym}: unexpected error — {exc}"
                result.errors.append(msg)
                log.warning(
                    "yfinance_earnings.unexpected_error", symbol=sym, error=str(exc)
                )
                continue

            if earnings_date is None:
                log.debug("yfinance_earnings.no_upcoming", symbol=sym)
                continue

            result.events.append(
                ProviderEvent(
                    symbol=sym,
                    event_type="earnings",
                    event_date=earnings_date,
                    title=f"{sym} Earnings",
                    event_time=None,
                    confidence=confidence,
                    notes="Auto-synced via Yahoo Finance (yfinance).",
                )
            )
            log.info(
                "yfinance_earnings.found",
                symbol=sym,
                event_date=str(earnings_date),
                confidence=confidence,
            )

        return result
