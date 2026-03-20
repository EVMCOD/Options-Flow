"""
Mock options data provider.

Generates realistic option chains with:
- 2–4 near-term expiry dates (next Fridays)
- ATM ± 10 strikes at $5 intervals
- Realistic bid/ask spreads and volumes
- 5–10 % of strikes randomly spike (volume 5–20x baseline)
- Occasional high-conviction "unusual" OTM events
- Deterministic component via symbol seed + slight randomness per call
"""

import asyncio
import math
import random
from datetime import datetime, date, timedelta
from typing import List, Optional

import numpy as np

from app.providers.base import BaseOptionsDataProvider, OptionContract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_fridays(n: int = 4) -> List[date]:
    """Return the next n Fridays from today."""
    today = date.today()
    days_until_friday = (4 - today.weekday()) % 7  # 4 = Friday
    if days_until_friday == 0:
        days_until_friday = 7
    first_friday = today + timedelta(days=days_until_friday)
    return [first_friday + timedelta(weeks=i) for i in range(n)]


def _spot_seed(symbol: str) -> int:
    """Deterministic seed component from symbol string."""
    return sum(ord(c) * (i + 1) for i, c in enumerate(symbol))


# Approximate spot price per symbol — realistic ballpark figures
_BASE_SPOTS: dict[str, float] = {
    "SPY": 520.0,
    "QQQ": 445.0,
    "AAPL": 185.0,
    "NVDA": 875.0,
    "TSLA": 175.0,
    "MSFT": 415.0,
    "AMD": 155.0,
    "META": 510.0,
}

_DEFAULT_SPOT = 100.0

# Per-call slight random-walk state (module-level so it persists between fetches)
_spot_walk: dict[str, float] = {}


def _get_spot(symbol: str) -> float:
    """Return a slightly random-walked spot price for the symbol."""
    base = _BASE_SPOTS.get(symbol, _DEFAULT_SPOT)
    if symbol not in _spot_walk:
        _spot_walk[symbol] = base
    # ±0.3 % random walk each call
    _spot_walk[symbol] *= 1.0 + random.uniform(-0.003, 0.003)
    return round(_spot_walk[symbol], 2)


def _simple_iv(moneyness: float, dte: int) -> float:
    """
    Simplified volatility smile:
    - ATM IV ≈ 0.25
    - OTM tails rise with distance from ATM
    - Shorter DTE → higher near-term vol
    """
    atm_iv = 0.25 + random.uniform(-0.02, 0.02)
    smile_width = 0.015 * max(30 / max(dte, 1), 1.0)
    distance = abs(moneyness - 1.0)
    smile_component = smile_width * (distance ** 1.5) * 30
    dte_factor = max(1.0, 30.0 / max(dte, 1)) * 0.05
    iv = atm_iv + smile_component + dte_factor
    return float(np.clip(iv, 0.08, 1.20))


def _option_price(spot: float, strike: float, iv: float, dte: int, option_type: str) -> float:
    """
    Simplified BSM-like intrinsic + time value estimate.
    Not mathematically rigorous — good enough for realistic-looking prices.
    """
    t = max(dte, 1) / 365.0
    r = 0.045  # risk-free rate proxy
    sqt = math.sqrt(t)
    atm_premium = spot * iv * sqt * 0.4  # simplified theta/vega proxy

    if option_type == "C":
        intrinsic = max(spot - strike, 0.0)
    else:
        intrinsic = max(strike - spot, 0.0)

    moneyness = spot / strike
    otm_discount = max(0.0, 1.0 - abs(moneyness - 1.0) * 3.0)
    time_value = atm_premium * otm_discount

    price = intrinsic + time_value
    return max(price, 0.01)


def _bid_ask(mid: float) -> tuple[float, float]:
    """Generate realistic bid/ask spread around mid."""
    if mid < 1.0:
        half_spread = 0.05
    elif mid < 5.0:
        half_spread = 0.10
    elif mid < 20.0:
        half_spread = 0.20
    else:
        half_spread = mid * 0.01
    bid = round(max(0.01, mid - half_spread), 2)
    ask = round(mid + half_spread, 2)
    return bid, ask


class MockOptionsDataProvider(BaseOptionsDataProvider):
    """
    Realistic mock provider for development and testing.

    Generates consistent option chains with injected volume anomalies
    to ensure the signal engine has real events to detect.

    credentials: unused (no auth required for mock)
    config:      unused (behaviour controlled by module-level constants)

    Registration: done by ProviderRegistry._bootstrap() — mock.py has no
    dependency on the registry to avoid circular imports.
    """

    def provider_name(self) -> str:
        return "mock"

    def market_data_mode(self) -> str:
        return "mock"

    async def fetch_chain(self, symbol: str) -> List[OptionContract]:
        # Simulate a brief I/O delay (realistic for network calls)
        await asyncio.sleep(random.uniform(0.05, 0.15))

        seed = _spot_seed(symbol)
        rng = np.random.default_rng(seed ^ int(datetime.utcnow().timestamp() / 300))
        # ^ XOR with 5-minute bucket so the "random" part changes between scan runs
        # but is stable within a single run

        now = datetime.utcnow()
        spot = _get_spot(symbol)
        expiries = _next_fridays(n=random.choice([2, 3, 4]))

        contracts: List[OptionContract] = []

        # Decide which strike/expiry/type combos get a volume spike this run
        spike_budget = max(1, int(len(expiries) * 21 * 2 * 0.08))  # ~8 % of strikes
        unusual_budget = random.randint(1, 3)  # extra big unusual events

        strike_step = 5.0 if spot >= 50 else 2.5
        n_strikes = 10  # ATM ± 10 strikes each side

        all_candidates = []
        for expiry in expiries:
            dte = (expiry - date.today()).days
            atm_strike = round(spot / strike_step) * strike_step
            strikes = [atm_strike + (i - n_strikes) * strike_step for i in range(n_strikes * 2 + 1)]
            for strike in strikes:
                if strike <= 0:
                    continue
                for otype in ("C", "P"):
                    all_candidates.append((expiry, dte, strike, otype))

        # Randomly assign spikes
        spike_indices = set(rng.choice(len(all_candidates), size=min(spike_budget, len(all_candidates)), replace=False).tolist())
        unusual_indices = set(rng.choice(len(all_candidates), size=min(unusual_budget, len(all_candidates)), replace=False).tolist())

        for idx, (expiry, dte, strike, otype) in enumerate(all_candidates):
            moneyness = spot / strike
            iv = _simple_iv(moneyness, dte)
            mid = _option_price(spot, strike, iv, dte, otype)
            bid, ask = _bid_ask(mid)
            last = round((bid + ask) / 2 + random.uniform(-0.02, 0.02), 2)

            # Baseline volume: low for OTM, higher for near-ATM
            atm_distance = abs(moneyness - 1.0)
            base_vol = int(max(10, 300 * math.exp(-atm_distance * 8)))

            # Volume with noise
            volume = int(base_vol * rng.lognormal(0, 0.4))

            # Volume spike injection
            if idx in unusual_indices:
                # High-conviction unusual — OTM, large multiplier
                multiplier = random.uniform(15, 40)
                volume = int(volume * multiplier)
            elif idx in spike_indices:
                multiplier = random.uniform(5, 15)
                volume = int(volume * multiplier)

            volume = max(0, volume)

            # Open interest: generally much larger than daily volume
            oi_base = int(base_vol * rng.uniform(5, 100))
            open_interest = max(100, oi_base)

            contracts.append(
                OptionContract(
                    as_of_ts=now,
                    underlying_symbol=symbol,
                    expiry=expiry,
                    strike=round(strike, 2),
                    option_type=otype,
                    spot_price=round(spot, 4),
                    bid=bid,
                    ask=ask,
                    last=max(0.01, last),
                    volume=volume,
                    open_interest=open_interest,
                    implied_vol=round(iv, 4),
                    source="mock",
                )
            )

        return contracts
