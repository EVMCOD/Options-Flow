"""
IBKR Delayed Options Data Provider.

Connects to Interactive Brokers TWS or IB Gateway and fetches delayed options
data using the ib_insync library.

What this provider supports
---------------------------
- 15–20 min delayed snapshots via reqMarketDataType(3) (free, no subscription)
- Any equity/ETF underlying supported by IBKR SMART routing
- Configurable chain width: nearest N expiries × ATM ± M strikes
- Bid, ask, last, volume, open interest, implied vol (when available)
- Paper and live account connections (read-only mode, no order submission)

What this provider does NOT support (yet)
------------------------------------------
- Streaming / tick-by-tick real-time data (reconnect per scan cycle instead)
- Options on futures or indices with non-standard symbology (e.g., SPX)
- Full OPRA chains (deliberately filtered to control request volume)
- Pre/post market data
- Greeks beyond implied vol (delta, gamma, vega are skipped for now)
- Automatic subscription to live data (reqMarketDataType(1) requires a paid
  IBKR market data subscription)

Requirements
------------
    pip install ib_insync>=0.9.86

Prerequisites on the host running Options Flow Radar
------------------------------------------------------
1. IBKR TWS or IB Gateway must be running and reachable at host:port
2. API access must be enabled:
   TWS → Edit → Global Configuration → API → Settings
   → "Enable ActiveX and Socket Clients" checked
   → Uncheck "Read-Only API" if you want to test live (not required for delayed)
3. For paper accounts: IB Gateway paper port is typically 4002
4. For live accounts: IB Gateway live port is typically 4001

Credentials and config
-----------------------
POST /api/v1/tenants/{id}/providers with:
{
  "provider_type": "ibkr_delayed",
  "credentials_json": {
    "host":      "127.0.0.1",   // TWS/IB Gateway host
    "port":      4002,          // IB Gateway paper: 4002, live: 4001
                                // TWS paper: 7497,  live: 7496
    "client_id": 10             // Must be unique per concurrent connection
  },
  "config_json": {
    "use_delayed_data": true,   // true = 15-min delayed (free)
                                // false = live (requires market data subscription)
    "timeout_seconds": 30,      // per-operation timeout
    "max_expiries":    4,       // nearest N expiry dates to include
    "strike_count":    10,      // ATM ± N strikes (total 2N+1 strikes per expiry)
    "exchange":        "SMART", // IBKR routing (SMART works for most US equities/ETFs)
    "batch_size":      50       // contracts per market data batch (max ~100 for most accounts)
  }
}

Known limitations of IBKR delayed data as a signal source
----------------------------------------------------------
- 15–20 min delay means "unusual" flow may have already moved the market
- Volume figures are cumulative from market open, not per-scan-interval
- Open interest is from prior close — does not update intraday
- Implied vol from modelGreeks uses IBKR's own model, may differ from OPRA
- Delayed snapshot availability depends on exchange hours; outside hours the
  provider returns empty (not an error — per the BaseOptionsDataProvider contract)
- Client ID conflicts: if TWS/IB Gateway already has an active connection with
  the same client_id, the new connection will be rejected. Use unique client_ids
  per tenant or configure a pool of IDs in config_json if running multiple tenants.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone
from typing import Any, List, Optional

from app.core.logging_setup import get_logger
from app.providers.base import BaseOptionsDataProvider, OptionContract

log = get_logger(__name__)

_PROVIDER_NAME = "ibkr_delayed"

# reqMarketDataType values
_MDT_LIVE = 1
_MDT_DELAYED = 3
_MDT_DELAYED_FROZEN = 4  # last known delayed price when market is closed


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------

class IBKRProviderError(RuntimeError):
    """Base for all IBKR provider errors — raised when the run should be marked failed."""


class IBKRConnectionError(IBKRProviderError):
    """Raised when connection to TWS/IB Gateway cannot be established."""


class IBKRNotInstalledError(IBKRProviderError):
    """Raised when ib_insync is not installed."""


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class IBKRDelayedProvider(BaseOptionsDataProvider):
    """
    Interactive Brokers delayed options data provider.

    Uses ib_insync to connect read-only to TWS or IB Gateway and fetch a
    filtered options chain snapshot per symbol.

    Connection lifecycle: a fresh IB connection is opened and closed within
    each fetch_chain() call. This is intentionally simple — for a 5-minute
    scan cycle the connection overhead is negligible and avoids session state
    management between runs.

    See module docstring for full setup instructions and limitations.
    """

    def provider_name(self) -> str:
        return _PROVIDER_NAME

    def market_data_mode(self) -> str:
        return "delayed" if self.config.get("use_delayed_data", True) else "live"

    async def fetch_chain(self, symbol: str) -> List[OptionContract]:
        # ----------------------------------------------------------------
        # 1. Validate credentials
        # ----------------------------------------------------------------
        _symbol_start = time.monotonic()
        host = self.credentials.require("host")
        try:
            port = int(self.credentials.require("port"))
            client_id = int(self.credentials.require("client_id"))
        except ValueError as exc:
            raise IBKRProviderError(
                f"Invalid IBKR credentials — 'port' and 'client_id' must be integers. "
                f"Detail: {exc}"
            ) from exc

        # ----------------------------------------------------------------
        # 2. Read operational config
        # ----------------------------------------------------------------
        use_delayed: bool = bool(self.config.get("use_delayed_data", True))
        timeout: float = float(self.config.get("timeout_seconds", 30))
        max_expiries: int = int(self.config.get("max_expiries", 4))
        strike_count: int = int(self.config.get("strike_count", 10))
        exchange: str = str(self.config.get("exchange", "SMART"))
        batch_size: int = int(self.config.get("batch_size", 50))

        # ----------------------------------------------------------------
        # 3. Import ib_insync (soft dependency — optional install)
        # ----------------------------------------------------------------
        try:
            from ib_insync import IB, Option, Stock  # type: ignore[import]
        except ImportError as exc:
            raise IBKRNotInstalledError(
                "ib_insync is not installed. Install it with:\n"
                "    pip install ib_insync>=0.9.86\n"
                "TWS or IB Gateway must also be running and configured for API access."
            ) from exc

        ib = IB()

        try:
            # ----------------------------------------------------------------
            # 4. Connect (read-only — no order submission possible)
            # ----------------------------------------------------------------
            await _connect(ib, host, port, client_id, timeout)

            # ----------------------------------------------------------------
            # 5. Set market data type (delayed vs live)
            # ----------------------------------------------------------------
            mdt = _MDT_DELAYED if use_delayed else _MDT_LIVE
            ib.reqMarketDataType(mdt)
            log.info(
                "ibkr.session_ready",
                symbol=symbol,
                host=host,
                port=port,
                data_type="delayed" if use_delayed else "live",
            )

            # ----------------------------------------------------------------
            # 6. Qualify the underlying and get spot price
            # ----------------------------------------------------------------
            stock = Stock(symbol.upper(), exchange, "USD")
            qualified = await _with_timeout(
                ib.qualifyContractsAsync(stock), timeout, "qualify underlying"
            )
            if not qualified:
                log.warning("ibkr.qualify_underlying_failed", symbol=symbol, reason="IBKR could not resolve symbol as a tradeable equity; check symbol and exchange config")
                return []
            stock = qualified[0]

            spot = await _fetch_spot(ib, stock, timeout)
            if spot is None:
                # No price available — market may be closed or symbol unsupported.
                # Return empty (not an error) per BaseOptionsDataProvider contract.
                log.info(
                    "ibkr.no_spot_price",
                    symbol=symbol,
                    reason="no_spot_price",
                    note="Delayed data unavailable — market may be closed or symbol has no delayed data feed. Empty result is normal outside trading hours.",
                )
                return []

            # ----------------------------------------------------------------
            # 7. Fetch available option parameters (strikes + expiries)
            # ----------------------------------------------------------------
            chains = await _with_timeout(
                ib.reqSecDefOptParamsAsync(
                    symbol.upper(), "", stock.secType, stock.conId
                ),
                timeout,
                "reqSecDefOptParams",
            )
            if not chains:
                log.warning("ibkr.no_option_params", symbol=symbol, reason="reqSecDefOptParams returned no chains — symbol may lack listed options or exchange config is wrong")
                return []

            chain = _select_chain(chains, exchange)
            if chain is None:
                log.warning(
                    "ibkr.no_chain_for_exchange",
                    symbol=symbol,
                    exchange=exchange,
                    available=[c.exchange for c in chains],
                    reason="no chain matched the configured exchange and fallback also failed",
                )
                return []

            # ----------------------------------------------------------------
            # 8. Filter to a manageable universe
            # ----------------------------------------------------------------
            today = date.today()
            sorted_expiries = sorted(
                exp for exp in chain.expirations
                if _parse_ibkr_expiry(exp) is not None
                and _parse_ibkr_expiry(exp) > today
            )
            selected_expiries = sorted_expiries[:max_expiries]

            all_strikes = sorted(float(s) for s in chain.strikes if float(s) > 0)
            selected_strikes = _nearest_strikes(all_strikes, spot, strike_count)

            if not selected_expiries or not selected_strikes:
                log.warning(
                    "ibkr.empty_universe",
                    symbol=symbol,
                    expiry_count=len(selected_expiries),
                    strike_count_filtered=len(selected_strikes),
                    reason="all expiries are in the past or no strikes within configured ATM range",
                )
                return []

            total = len(selected_expiries) * len(selected_strikes) * 2
            log.info(
                "ibkr.fetching_chain",
                symbol=symbol,
                expiries=len(selected_expiries),
                strikes=len(selected_strikes),
                total_contracts=total,
            )

            # ----------------------------------------------------------------
            # 9. Build, qualify, and snapshot the option contracts
            # ----------------------------------------------------------------
            raw_options = [
                Option(symbol.upper(), exp, strike, right, exchange)
                for exp in selected_expiries
                for strike in selected_strikes
                for right in ("C", "P")
            ]

            qualified_options = await _qualify_batched(ib, raw_options, batch_size, timeout)
            if not qualified_options:
                log.warning("ibkr.no_qualified_contracts", symbol=symbol)
                return []

            tickers = await _snapshot_batched(ib, qualified_options, batch_size, timeout)

            # ----------------------------------------------------------------
            # 10. Map tickers → OptionContract
            # ----------------------------------------------------------------
            now = datetime.now(tz=timezone.utc)
            result: List[OptionContract] = []
            skipped = 0

            for ticker in tickers:
                oc = _map_ticker(ticker, spot, now)
                if oc is not None:
                    result.append(oc)
                else:
                    skipped += 1

            log.info(
                "ibkr.chain_complete",
                symbol=symbol,
                returned=len(result),
                skipped_no_data=skipped,
            )
            log.info(
                "ibkr.fetch_complete",
                symbol=symbol,
                elapsed_s=round(time.monotonic() - _symbol_start, 2),
                contracts_returned=len(result),
            )
            return result

        finally:
            if ib.isConnected():
                ib.disconnect()
                log.debug("ibkr.disconnected", symbol=symbol)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

async def _connect(
    ib: Any,
    host: str,
    port: int,
    client_id: int,
    timeout: float,
) -> None:
    """Establish a read-only connection, raising clear errors on failure."""
    try:
        await asyncio.wait_for(
            ib.connectAsync(host, port, clientId=client_id, readonly=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise IBKRConnectionError(
            f"Timed out connecting to TWS/IB Gateway at {host}:{port} "
            f"(timeout={timeout}s). "
            f"Ensure TWS or IB Gateway is running and API sockets are enabled."
        )
    except (ConnectionRefusedError, OSError) as exc:
        raise IBKRConnectionError(
            f"Connection refused by TWS/IB Gateway at {host}:{port}: {exc}. "
            f"Checklist:\n"
            f"  1. TWS or IB Gateway is running\n"
            f"  2. API → Settings → 'Enable ActiveX and Socket Clients' is checked\n"
            f"  3. The configured port matches your TWS/IB Gateway setting\n"
            f"  4. Trusted IP list includes {host} (or is set to allow all)"
        ) from exc


# ---------------------------------------------------------------------------
# Spot price
# ---------------------------------------------------------------------------

async def _fetch_spot(ib: Any, stock: Any, timeout: float) -> Optional[float]:
    """
    Request a stock ticker snapshot and extract the best available price.

    Preference: last > close > bid-ask midpoint.
    Returns None if no usable price is available (market closed, no delayed feed).
    """
    try:
        tickers = await _with_timeout(ib.reqTickersAsync(stock), timeout, "spot price")
        if not tickers:
            return None
        t = tickers[0]
    except Exception as exc:
        log.warning("ibkr.spot_fetch_error", error=str(exc))
        return None

    for price_attr in ("last", "close"):
        val = _safe_float(getattr(t, price_attr, None))
        if val is not None and val > 0:
            return val

    bid = _safe_float(t.bid)
    ask = _safe_float(t.ask)
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0

    return None


# ---------------------------------------------------------------------------
# Chain parameter helpers
# ---------------------------------------------------------------------------

def _parse_ibkr_expiry(exp_str: str) -> Optional[date]:
    """Parse IBKR expiry string 'YYYYMMDD' → date. Returns None on bad input."""
    try:
        if len(exp_str) != 8:
            return None
        return date(int(exp_str[:4]), int(exp_str[4:6]), int(exp_str[6:8]))
    except (ValueError, TypeError):
        return None


def _select_chain(chains: list, preferred_exchange: str) -> Optional[Any]:
    """
    Pick the best chain params from reqSecDefOptParams results.

    Prefers the requested exchange; falls back to the first available.
    Logs if falling back so the operator knows the exchange preference wasn't met.
    """
    for c in chains:
        if c.exchange == preferred_exchange:
            return c
    if chains:
        log.info(
            "ibkr.chain_exchange_fallback",
            preferred=preferred_exchange,
            using=chains[0].exchange,
            available=[c.exchange for c in chains],
        )
        return chains[0]
    return None


def _nearest_strikes(strikes: List[float], spot: float, count: int) -> List[float]:
    """
    Return up to (2 * count + 1) strikes centred around ATM.

    For SPY (spot ~520, $1 increments, count=10): 21 strikes.
    For AAPL (spot ~185, $2.5 increments, count=10): 21 strikes.
    """
    if not strikes:
        return []
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo = max(0, atm_idx - count)
    hi = min(len(strikes), atm_idx + count + 1)
    return strikes[lo:hi]


# ---------------------------------------------------------------------------
# Batched API calls
# ---------------------------------------------------------------------------

async def _with_timeout(coro: Any, timeout: float, label: str) -> Any:
    """Run a coroutine with a timeout, logging on expiry."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("ibkr.timeout", operation=label, timeout_s=timeout)
        raise IBKRProviderError(
            f"IBKR operation '{label}' timed out after {timeout}s. "
            f"Consider increasing 'timeout_seconds' in config_json."
        )


async def _qualify_batched(
    ib: Any, contracts: list, batch_size: int, timeout: float
) -> list:
    """
    Qualify contracts in batches.

    Contracts that don't exist (e.g., a strike that was in reqSecDefOptParams
    but has since been delisted) are silently dropped — their conId stays 0.
    """
    qualified: list = []
    for i in range(0, len(contracts), batch_size):
        batch = contracts[i : i + batch_size]
        try:
            result = await asyncio.wait_for(
                ib.qualifyContractsAsync(*batch),
                timeout=timeout,
            )
            qualified.extend(c for c in result if getattr(c, "conId", 0))
        except asyncio.TimeoutError:
            log.warning(
                "ibkr.qualify_batch_timeout",
                batch_start=i,
                batch_size=len(batch),
            )
        except Exception as exc:
            log.warning(
                "ibkr.qualify_batch_error",
                batch_start=i,
                error=str(exc),
            )
    return qualified


async def _snapshot_batched(
    ib: Any, contracts: list, batch_size: int, timeout: float
) -> list:
    """
    Request delayed market data snapshots in batches.

    IBKR limits concurrent market data lines (~100 for most accounts). Using
    batch_size=50 leaves headroom for the underlying spot request and other
    system activity.

    Batches that time out or error are skipped — the run will still return
    partial data for earlier batches, which is better than failing entirely.
    """
    tickers: list = []
    for i in range(0, len(contracts), batch_size):
        batch = contracts[i : i + batch_size]
        try:
            result = await asyncio.wait_for(
                ib.reqTickersAsync(*batch),
                timeout=timeout,
            )
            tickers.extend(result)
        except asyncio.TimeoutError:
            log.warning(
                "ibkr.snapshot_batch_timeout",
                batch_start=i,
                batch_size=len(batch),
            )
        except Exception as exc:
            log.warning(
                "ibkr.snapshot_batch_error",
                batch_start=i,
                error=str(exc),
            )
    return tickers


# ---------------------------------------------------------------------------
# Ticker → OptionContract mapping
# ---------------------------------------------------------------------------

def _map_ticker(ticker: Any, spot: float, now: datetime) -> Optional[OptionContract]:
    """
    Map an ib_insync Ticker (options snapshot) to an OptionContract.

    Returns None when essential price data is entirely absent — these contracts
    are counted in the 'skipped_no_data' log field and excluded from the run.

    Notes on field availability with delayed snapshots:
    - bid / ask: usually populated even in delayed mode
    - last:      may be None if no trade occurred today
    - volume:    day volume from market open; float in ib_insync, cast to int
    - open_interest: prior-close OI; requires tick type 101; may be 0 if
                    not yet propagated in the delayed feed
    - implied_vol: from modelGreeks.impliedVol; may be None if IBKR's model
                  hasn't computed it for this contract yet
    """
    c = ticker.contract

    # Parse contract metadata
    try:
        expiry = _parse_ibkr_expiry(c.lastTradeDateOrContractMonth)
        if expiry is None:
            return None
        strike = float(c.strike)
        right = c.right  # "C" or "P"
    except (AttributeError, ValueError, TypeError):
        return None

    if right not in ("C", "P"):
        return None

    # Extract prices — all may be NaN in ib_insync when data is unavailable
    bid = _safe_float(getattr(ticker, "bid", None))
    ask = _safe_float(getattr(ticker, "ask", None))
    last = _safe_float(getattr(ticker, "last", None))
    close = _safe_float(getattr(ticker, "close", None))

    # Require at least one price to produce a meaningful record
    if bid is None and ask is None and last is None and close is None:
        return None

    # Fill in missing values with reasonable proxies
    mid = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    if last is None:
        last = mid or close or (bid or 0.01) + 0.05
    if bid is None:
        bid = max(0.01, (last or 0.05) - 0.05)
    if ask is None:
        ask = (last or 0.01) + 0.05

    volume = int(_safe_float(getattr(ticker, "volume", None)) or 0)

    # open_interest: ib_insync exposes this on the Ticker object when tick type
    # 101 has been received. With delayed snapshots it may arrive or be 0.
    open_interest = int(_safe_float(getattr(ticker, "openInterest", None)) or 0)

    # Implied vol from IBKR's internal model (available when modelGreeks is populated)
    implied_vol: Optional[float] = None
    greeks = getattr(ticker, "modelGreeks", None)
    if greeks is not None:
        iv = _safe_float(getattr(greeks, "impliedVol", None))
        if iv is not None and 0.001 < iv < 50.0:  # sanity range: 0.1% – 5000%
            implied_vol = round(iv, 4)

    return OptionContract(
        as_of_ts=now,
        underlying_symbol=c.symbol,
        expiry=expiry,
        strike=round(strike, 2),
        option_type=right,
        spot_price=round(float(spot), 4),
        bid=round(float(bid), 4),
        ask=round(float(ask), 4),
        last=round(float(last), 4),
        volume=volume,
        open_interest=open_interest,
        implied_vol=implied_vol,
        source=_PROVIDER_NAME,
    )


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
    """
    Convert value to float, returning None for invalid/missing data.

    ib_insync uses float('nan') as a sentinel for 'no data' — this handles it.
    Negative prices are also rejected (they indicate 'no data' in some contexts).
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check: NaN is the only float not equal to itself
        return None
    return f if f >= 0 else None
