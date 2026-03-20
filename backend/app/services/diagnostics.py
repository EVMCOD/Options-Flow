"""
Provider diagnostics service.

Runs a test fetch against a provider config and computes data quality metrics.
Nothing is stored to the database — this is a pure read-only diagnostic tool.

Key contract:
  - run_provider_test() resolves the provider, fetches each requested symbol,
    and returns a ProviderTestReport.
  - No side effects: no IngestionRun created, no snapshots stored.
  - Credentials are never included in the report.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.core.logging_setup import get_logger
from app.providers.base import OptionContract
from app.providers.registry import ProviderRegistry
from app.schemas.schemas import (
    ContractSample,
    ProviderTestReport,
    SymbolDiagnostics,
)
from app.tenants.models import TenantProviderConfig

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Per-contract quality helpers
# ---------------------------------------------------------------------------

def _quality_gate(c: OptionContract) -> bool:
    """
    Same gate as ingestion.py: skip if no usable price at all.
    A contract with bid=0.01 proxy and ask=0.06 proxy but last=0.01 is garbage.
    """
    mid = (c.bid + c.ask) / 2.0
    return not (mid < 0.02 and c.last < 0.02)


def _data_flags(c: OptionContract) -> List[str]:
    """Return human-readable flags for fields that are missing or estimated."""
    flags = []
    if c.open_interest == 0:
        flags.append("no_oi")
    if c.implied_vol is None:
        flags.append("no_iv")
    if c.bid <= 0.01:
        flags.append("est_bid")   # bid was below the proxy floor
    if c.ask <= 0.01:
        flags.append("est_ask")
    if c.volume == 0:
        flags.append("no_vol")
    return flags


def _build_sample(c: OptionContract) -> ContractSample:
    return ContractSample(
        symbol=c.underlying_symbol,
        expiry=c.expiry.isoformat(),
        strike=c.strike,
        option_type=c.option_type,
        bid=round(c.bid, 4),
        ask=round(c.ask, 4),
        last=round(c.last, 4),
        volume=c.volume,
        open_interest=c.open_interest,
        implied_vol=c.implied_vol,
        data_flags=_data_flags(c),
    )


def _build_symbol_diagnostics(
    symbol: str,
    contracts: List[OptionContract],
    elapsed_ms: int,
    status: str,
    empty_reason: Optional[str] = None,
    error_detail: Optional[str] = None,
) -> SymbolDiagnostics:
    quality_passed = [c for c in contracts if _quality_gate(c)]

    missing_vol = sum(1 for c in contracts if c.volume == 0)
    missing_oi = sum(1 for c in contracts if c.open_interest == 0)
    missing_iv = sum(1 for c in contracts if c.implied_vol is None)
    missing_bid = sum(1 for c in contracts if c.bid <= 0.01)
    missing_ask = sum(1 for c in contracts if c.ask <= 0.01)
    missing_last = sum(1 for c in contracts if c.last <= 0.01)

    # Sample: up to 3, preferring contracts with highest volume + OI
    sample_pool = sorted(
        quality_passed,
        key=lambda c: -(c.volume + c.open_interest),
    )[:3]

    return SymbolDiagnostics(
        symbol=symbol,
        elapsed_ms=elapsed_ms,
        status=status,
        empty_reason=empty_reason,
        error_detail=error_detail,
        contracts_returned=len(contracts),
        contracts_quality_passed=len(quality_passed),
        missing_volume=missing_vol,
        missing_open_interest=missing_oi,
        missing_iv=missing_iv,
        missing_bid=missing_bid,
        missing_ask=missing_ask,
        missing_last=missing_last,
        sample_contracts=[_build_sample(c) for c in sample_pool],
    )


# ---------------------------------------------------------------------------
# Quality verdict
# ---------------------------------------------------------------------------

def _compute_quality_verdict(
    symbols_with_data: int,
    symbols_tested: int,
    total_returned: int,
    pct_bid_ask: float,
    pct_oi: float,
    pct_iv: float,
    avg_contracts: float,
    market_data_mode: str,
) -> Tuple[str, List[str]]:
    notes: List[str] = []

    if symbols_with_data == 0:
        notes.append(
            "All symbols returned empty — market may be closed or delayed data "
            "unavailable outside trading hours (09:30–16:00 ET)."
        )
        return "poor", notes

    if total_returned == 0:
        return "poor", ["No contracts returned."]

    # Verdict based on price coverage and chain width
    if pct_bid_ask < 0.50 or avg_contracts < 1:
        verdict = "poor"
        notes.append(
            f"Bid/ask coverage very low ({pct_bid_ask:.0%}) — "
            "prices unreliable, signals would not be trustworthy."
        )
    elif pct_bid_ask < 0.80 or avg_contracts < 10:
        verdict = "limited"
        if pct_bid_ask < 0.80:
            notes.append(f"Bid/ask coverage moderate ({pct_bid_ask:.0%}).")
        if avg_contracts < 10:
            notes.append(
                f"Low contract count (avg {avg_contracts:.0f}/symbol) — "
                "consider increasing 'strike_count' or 'max_expiries' in config_json."
            )
    elif pct_bid_ask < 0.95:
        verdict = "usable"
    else:
        verdict = "good"

    # Informational notes regardless of verdict
    if pct_oi < 0.20:
        notes.append(
            f"Open interest sparse ({pct_oi:.0%} populated) — expected with "
            "delayed feed. The OI component of the anomaly score (20% weight) will be zero."
        )
    elif pct_oi < 0.60:
        notes.append(f"Open interest partially populated ({pct_oi:.0%}).")

    if pct_iv < 0.50:
        notes.append(
            f"Implied vol missing for {(1.0 - pct_iv):.0%} of contracts — "
            "normal for far OTM and short-DTE strikes."
        )

    if avg_contracts > 0 and avg_contracts < 30:
        notes.append(
            f"Chain width: avg {avg_contracts:.0f} contracts/symbol. "
            "Increase 'strike_count' in config_json for broader coverage."
        )

    if market_data_mode == "delayed":
        notes.append(
            "15–20 min delayed data. Volume = cumulative day volume from market open, "
            "not per-interval flow. OI = prior-close value."
        )

    return verdict, notes


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_provider_test(
    config: TenantProviderConfig,
    symbols: List[str],
) -> ProviderTestReport:
    """
    Execute a diagnostic test fetch for the given provider config and symbols.

    Calls fetch_chain() for each symbol, collects detailed quality metrics,
    and returns a ProviderTestReport.

    This function has NO side effects:
    - No IngestionRun is created.
    - No snapshots are stored.
    - Credentials are excluded from the report output.

    The call is synchronous from the caller's perspective (awaited) but may
    take up to timeout_seconds × len(symbols) depending on provider latency.
    For IBKR, budget 30–60 seconds per symbol.
    """
    report_start = time.monotonic()
    tested_at = datetime.now(tz=timezone.utc)

    provider = ProviderRegistry.resolve(config)
    market_data_mode = provider.market_data_mode()

    # config_effective: expose config_json (non-sensitive) + key metadata.
    # credentials_json is intentionally excluded.
    config_effective: dict = {
        "provider_type": config.provider_type,
        "is_active": config.is_active,
        "is_default": config.is_default,
        "current_status": config.status,
        "market_data_mode": market_data_mode,
        **(config.config_json or {}),
    }

    per_symbol: List[SymbolDiagnostics] = []
    symbols_with_data = 0
    symbols_empty = 0
    symbols_errored = 0
    total_returned = 0
    total_quality_passed = 0

    for symbol in symbols:
        sym_start = time.monotonic()
        contracts: List[OptionContract] = []
        status = "ok"
        empty_reason: Optional[str] = None
        error_detail: Optional[str] = None

        try:
            contracts = await provider.fetch_chain(symbol)
            elapsed_ms = int((time.monotonic() - sym_start) * 1000)

            if contracts:
                symbols_with_data += 1
            else:
                symbols_empty += 1
                status = "empty"
                empty_reason = (
                    "provider returned 0 contracts — "
                    "market may be closed or no delayed data for this symbol"
                )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - sym_start) * 1000)
            symbols_errored += 1
            status = "error"
            error_detail = str(exc)
            log.warning(
                "diagnostics.symbol_error",
                symbol=symbol,
                provider_type=config.provider_type,
                error=str(exc),
            )

        quality_passed = [c for c in contracts if _quality_gate(c)]
        total_returned += len(contracts)
        total_quality_passed += len(quality_passed)

        per_symbol.append(
            _build_symbol_diagnostics(
                symbol=symbol,
                contracts=contracts,
                elapsed_ms=elapsed_ms,
                status=status,
                empty_reason=empty_reason,
                error_detail=error_detail,
            )
        )

    symbols_tested = len(symbols)
    avg_contracts = total_returned / symbols_tested if symbols_tested > 0 else 0.0

    # Aggregate null rates
    total_missing_vol = sum(s.missing_volume for s in per_symbol)
    total_missing_oi = sum(s.missing_open_interest for s in per_symbol)
    total_missing_iv = sum(s.missing_iv for s in per_symbol)

    def _pct(missing: int) -> float:
        return round(1.0 - missing / total_returned, 4) if total_returned > 0 else 0.0

    # pct_usable_bid_ask: fraction that passed the quality gate (has any usable price)
    pct_bid_ask = round(total_quality_passed / total_returned, 4) if total_returned > 0 else 0.0
    pct_vol = _pct(total_missing_vol)
    pct_oi = _pct(total_missing_oi)
    pct_iv = _pct(total_missing_iv)

    quality_verdict, quality_notes = _compute_quality_verdict(
        symbols_with_data=symbols_with_data,
        symbols_tested=symbols_tested,
        total_returned=total_returned,
        pct_bid_ask=pct_bid_ask,
        pct_oi=pct_oi,
        pct_iv=pct_iv,
        avg_contracts=avg_contracts,
        market_data_mode=market_data_mode,
    )

    return ProviderTestReport(
        tested_at=tested_at,
        elapsed_ms=int((time.monotonic() - report_start) * 1000),
        tenant_id=str(config.tenant_id),
        config_id=str(config.id),
        provider_type=config.provider_type,
        market_data_mode=market_data_mode,
        config_effective=config_effective,
        symbols_requested=symbols,
        symbols_with_data=symbols_with_data,
        symbols_empty=symbols_empty,
        symbols_errored=symbols_errored,
        total_contracts_returned=total_returned,
        total_contracts_quality_passed=total_quality_passed,
        avg_contracts_per_symbol=round(avg_contracts, 1),
        pct_usable_bid_ask=pct_bid_ask,
        pct_usable_volume=pct_vol,
        pct_usable_oi=pct_oi,
        pct_usable_iv=pct_iv,
        quality_verdict=quality_verdict,
        quality_notes=quality_notes,
        per_symbol=per_symbol,
    )
