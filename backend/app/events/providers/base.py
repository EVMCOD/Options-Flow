"""
Base contract for all event calendar providers.

To add a new provider:
  1. Subclass BaseEventProvider in a new file under app/events/providers/
  2. Implement name, supported_types, and fetch()
  3. Register the instance in app/events/service.py _PROVIDERS list

The service layer handles all DB interaction and conflict resolution.
Providers only fetch and return ProviderEvent objects — no DB access.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class ProviderEvent:
    """
    Normalised event returned by any event provider.

    Crosses the provider → service boundary.  The service maps this to a
    SymbolEvent model row, applying the conflict policy before writing to DB.
    """

    symbol: str
    event_type: str           # "earnings", "fda_decision", "macro", etc.
    event_date: date
    title: str
    event_time: Optional[str] = None    # "AMC", "BMO", "during_market", None
    source: str = ""                    # set to provider.name by the service
    confidence: float = 1.0             # 0.0–1.0; 0.5 = estimated, 1.0 = confirmed
    notes: Optional[str] = None


@dataclass
class ProviderFetchResult:
    """
    Outcome of one provider.fetch() call.

    Returned by fetch() so callers can distinguish between a provider that
    genuinely found nothing and one that failed partway through.
    """

    events: List[ProviderEvent] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class BaseEventProvider(ABC):
    """
    Abstract base for all event calendar providers.

    Implementations should be stateless and side-effect-free: they only reach
    out to external APIs and return ProviderEvent objects.  The service layer
    owns DB writes, upsert logic, and transaction management.

    fetch() must not raise: it should catch internal errors, add them to
    ProviderFetchResult.errors, and return what it has so far.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Short identifier for this provider.
        Written to SymbolEvent.source on create and to EventSyncResult.provider
        in the sync report.  Must be stable across restarts (used as a DB key).
        Example: "yfinance", "benzinga", "fda_calendar"
        """
        ...

    @property
    @abstractmethod
    def supported_types(self) -> List[str]:
        """
        Event types this provider can supply.
        Example: ["earnings"], ["fda_decision", "pdufa"], ["fomc", "cpi"]
        Used by the service to route type-filtered requests to the right provider.
        """
        ...

    @abstractmethod
    async def fetch(self, symbols: List[str]) -> ProviderFetchResult:
        """
        Fetch upcoming events for the given symbols.

        Args:
            symbols: Uppercase ticker symbols, e.g. ["AAPL", "NVDA"].

        Returns:
            ProviderFetchResult with .events (may be empty) and .errors
            (empty on full success, populated on partial or total failure).

        Contract:
          - MUST NOT raise exceptions — catch internally and add to .errors.
          - MUST NOT write to the database.
          - MAY return duplicate symbols if the external source does.
            The service deduplicates via the conflict policy.
          - events[*].source is left empty; the service stamps it with self.name.
        """
        ...
