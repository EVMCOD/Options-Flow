"""
Base contract for all options data providers.

To implement a new provider:
  1. Subclass BaseOptionsDataProvider
  2. Implement fetch_chain() and provider_name()
  3. Import in app/providers/registry.py _bootstrap() and register
  4. POST to /api/v1/tenants/{id}/providers with the new provider_type

The provider receives credentials and config from TenantProviderConfig,
so no provider-specific secrets live in global settings or source code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Optional

from app.providers.credentials import ProviderCredentials


@dataclass
class OptionContract:
    """
    Normalised representation of a single options contract snapshot.

    This is the canonical data unit that crosses the provider boundary.
    All provider implementations must map their native format to this struct
    before returning from fetch_chain().
    """
    as_of_ts: datetime
    underlying_symbol: str
    expiry: date
    strike: float
    option_type: str       # 'C' (call) or 'P' (put)
    spot_price: float
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_vol: Optional[float]
    source: str            # provider identifier, e.g. "mock", "polygon"


class BaseOptionsDataProvider(ABC):
    """
    Abstract base for all market data providers.

    ProviderRegistry.resolve(config) returns a concrete instance with the
    credentials and config from the tenant's TenantProviderConfig record.
    The pipeline never needs to know which provider it is talking to.
    """

    def __init__(
        self,
        credentials: dict | None = None,
        config: dict | None = None,
    ) -> None:
        """
        Args:
            credentials: Provider auth material (API keys, tokens, etc.).
                         Wrapped in ProviderCredentials — never appears in
                         repr(), logs, or tracebacks. Keys are provider-specific.
            config:      Non-sensitive operational settings (timeouts, rate
                         limits, sandbox flags, etc.).
        """
        # Use ProviderCredentials wrapper so credentials are never exposed in
        # log output. Access via self.credentials.require("key") or .get("key").
        self.credentials: ProviderCredentials = ProviderCredentials(credentials or {})
        self.config: dict = config or {}

    @abstractmethod
    async def fetch_chain(self, symbol: str) -> List[OptionContract]:
        """
        Fetch the full options chain for a given underlying symbol.

        Contract:
          - Must return all available expiries and strikes for the symbol.
          - Empty list is valid (e.g., market closed, no data) — do not raise.
          - Raise only on unrecoverable errors (auth failure, network timeout
            after retries). The ingestion service wraps each symbol in a
            try/except and will record the error in IngestionRun.error_message.
        """
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier written to the `source` field of each contract."""
        ...

    def market_data_mode(self) -> str:
        """
        Short label describing the data freshness mode for this provider instance.
        Stamped on IngestionRun for auditing. Override in each concrete provider.

        Standard values: "live" | "delayed" | "mock"
        """
        return "live"
