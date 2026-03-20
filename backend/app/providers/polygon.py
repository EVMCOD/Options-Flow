"""
Polygon.io options data provider.

Authentication
--------------
Requires an API key with options data access (Starter plan or above).
Pass via TenantProviderConfig credentials_json:

    {"api_key": "your_polygon_api_key"}

Operational config_json options (all optional):

    {
        "request_timeout_s": 30,    # HTTP timeout per request
        "rate_limit_rps": 5,        # requests per second (Starter: 5 rps)
        "max_expiries": 6           # limit chains to the nearest N expiry dates
    }

API used
--------
- Snapshot: GET /v3/snapshot/options/{underlying_symbol}
  Docs: https://polygon.io/docs/options/get_v3_snapshot_options__underlyingasset

Mapping
-------
Polygon response field → OptionContract field
  details.expiration_date → expiry
  details.strike_price    → strike
  details.contract_type   → option_type ("call"→"C", "put"→"P")
  day.volume              → volume
  day.open_interest       → open_interest (via open_interest field)
  day.vwap                → last (proxy; Polygon does not return "last" in snapshot)
  greeks.implied_volatility → implied_vol
  underlying_asset.price  → spot_price
  day.session.close / day.last_quote.bid / ask → bid / ask

Production checklist
--------------------
1. Handle 429 (rate limit) with exponential backoff.
2. Paginate: Polygon returns max 250 contracts per page; follow `next_url`.
3. Add a `max_expiries` filter to avoid pulling the full multi-year chain on liquid names.
4. Consider caching spot_price per symbol (same for all contracts in one fetch).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from app.providers.base import BaseOptionsDataProvider, OptionContract


_SNAPSHOT_URL = "https://api.polygon.io/v3/snapshot/options/{symbol}"
_DEFAULT_TIMEOUT = 30
_DEFAULT_RATE_LIMIT_RPS = 5
_DEFAULT_MAX_EXPIRIES = 6


class PolygonOptionsDataProvider(BaseOptionsDataProvider):
    """
    Polygon.io provider — production-ready scaffold.

    Authentication is read from self.credentials.require("api_key").
    The provider is stateless between fetch_chain() calls; create a new
    httpx.AsyncClient per call so each fetch respects request timeouts cleanly.
    """

    def provider_name(self) -> str:
        return "polygon"

    async def fetch_chain(self, symbol: str) -> List[OptionContract]:
        api_key = self.credentials.require("api_key")
        timeout = self.config.get("request_timeout_s", _DEFAULT_TIMEOUT)
        max_expiries = self.config.get("max_expiries", _DEFAULT_MAX_EXPIRIES)

        contracts: List[OptionContract] = []
        url: Optional[str] = _SNAPSHOT_URL.format(symbol=symbol.upper())

        async with httpx.AsyncClient(timeout=timeout) as client:
            while url is not None:
                resp = await client.get(
                    url,
                    params={"apiKey": api_key, "limit": 250},
                )

                if resp.status_code == 401:
                    raise PermissionError(
                        f"Polygon authentication failed for key ending in "
                        f"...{api_key[-4:]}. Check credentials."
                    )
                if resp.status_code == 403:
                    raise PermissionError(
                        "Polygon returned 403: options data may require a paid plan."
                    )
                resp.raise_for_status()

                payload = resp.json()
                results = payload.get("results", []) or []

                for item in results:
                    contract = _parse_contract(item, symbol)
                    if contract is not None:
                        contracts.append(contract)

                url = payload.get("next_url")
                if url:
                    # Respect rate limit between paginated requests
                    rps = self.config.get("rate_limit_rps", _DEFAULT_RATE_LIMIT_RPS)
                    await asyncio.sleep(1.0 / max(rps, 1))

        return contracts


def _parse_contract(item: dict, underlying_symbol: str) -> Optional[OptionContract]:
    """
    Map a single Polygon snapshot result dict to an OptionContract.

    Returns None if required fields are missing (contract is skipped silently).
    """
    try:
        details = item.get("details", {})
        day = item.get("day", {})
        greeks = item.get("greeks", {})
        underlying = item.get("underlying_asset", {})
        last_quote = item.get("last_quote", {})

        expiry_str = details.get("expiration_date")  # "2025-06-20"
        strike = details.get("strike_price")
        contract_type = details.get("contract_type", "").lower()  # "call" or "put"

        if not expiry_str or strike is None or contract_type not in ("call", "put"):
            return None

        option_type = "C" if contract_type == "call" else "P"

        volume = int(day.get("volume") or 0)
        open_interest = int(item.get("open_interest") or 0)
        spot_price = float(underlying.get("price") or 0.0)

        bid = float(last_quote.get("bid") or 0.0)
        ask = float(last_quote.get("ask") or 0.0)
        last = float(day.get("vwap") or day.get("close") or 0.0)

        implied_vol_raw = greeks.get("implied_volatility")
        implied_vol = float(implied_vol_raw) if implied_vol_raw is not None else None

        from datetime import date
        expiry = date.fromisoformat(expiry_str)

        return OptionContract(
            as_of_ts=datetime.now(tz=timezone.utc),
            underlying_symbol=underlying_symbol.upper(),
            expiry=expiry,
            strike=float(strike),
            option_type=option_type,
            spot_price=spot_price,
            bid=bid,
            ask=ask,
            last=last,
            volume=volume,
            open_interest=open_interest,
            implied_vol=implied_vol,
            source="polygon",
        )

    except (TypeError, ValueError, KeyError):
        return None
