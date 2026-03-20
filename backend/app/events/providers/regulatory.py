"""
Regulatory event provider — scaffold.

Intended to surface FDA PDUFA dates, EMA decisions, and similar drug-approval
catalysts for biotech/pharma symbols.

Status: NOT IMPLEMENTED
────────────────────────
This file is a scaffold.  fetch() raises NotImplementedError until a concrete
data source is wired in.

Candidate sources (V2 roadmap):
  · BioPharma Catalyst (free RSS / JSON feed)
  · FDA.gov PDUFA calendar (HTML scrape — fragile)
  · Benzinga calendar API (paid)
  · Manual seed via POST /api/v1/events/bulk with event_type="fda_decision"

To implement:
  1. Choose a data source.
  2. Implement _fetch_pdufa_dates_sync(symbols, today) similarly to the
     yfinance provider: synchronous HTTP call wrapped in asyncio.to_thread().
  3. Remove the NotImplementedError and return a ProviderFetchResult.
  4. Register in app/events/service.py _PROVIDERS (it's already listed as
     commented-out; just uncomment it).

Usage once implemented:
  POST /api/v1/jobs/sync-events?types=fda_decision&providers=regulatory
"""

from __future__ import annotations

from typing import List

from app.events.providers.base import BaseEventProvider, ProviderEvent, ProviderFetchResult  # noqa: F401


class RegulatoryEventProvider(BaseEventProvider):
    """
    Scaffold provider for FDA PDUFA dates and similar regulatory catalysts.
    Not yet implemented — see module docstring for roadmap.
    """

    @property
    def name(self) -> str:
        return "regulatory"

    @property
    def supported_types(self) -> List[str]:
        return ["fda_decision", "pdufa", "ema_opinion"]

    async def fetch(self, symbols: List[str]) -> ProviderFetchResult:
        raise NotImplementedError(
            "RegulatoryEventProvider is not yet implemented.  "
            "See app/events/providers/regulatory.py for implementation guidance."
        )
