#!/usr/bin/env python3
"""
Provider validation CLI.

Connects directly to the database (no API server needed), resolves the
tenant's default provider config, runs a diagnostic test fetch, and
prints a quality report to stdout.

Usage:
    cd backend/
    python scripts/validate_provider.py --tenant-id 00000000-0000-0000-0000-000000000001
    python scripts/validate_provider.py --tenant-id <UUID> --symbols SPY,QQQ
    python scripts/validate_provider.py --tenant-id <UUID> --max-symbols 3
    python scripts/validate_provider.py --config-id <UUID> --symbols SPY

Options:
    --tenant-id     UUID of the tenant to test (uses its default provider config)
    --config-id     UUID of a specific provider config to test directly
    --symbols       Comma-separated symbols, e.g. SPY,QQQ,AAPL
    --max-symbols   How many symbols to test from the tenant's universe (default: 2)
    --no-samples    Suppress the sample contract table

The default tenant UUID is printed by `GET /api/v1/tenants` if you're unsure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Optional

# Make sure the app package is importable when running from `backend/`
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging_setup import configure_logging
from app.models.models import ScannerUniverse
from app.providers.registry import ProviderRegistry  # noqa: F401 — populates registry
from app.schemas.schemas import ProviderTestReport, SymbolDiagnostics
from app.services.diagnostics import run_provider_test
from app.tenants.service import (
    get_active_provider_config,
    get_provider_config_by_id,
    get_tenant_by_id,
)


# ---------------------------------------------------------------------------
# Terminal formatting helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_DIM = "\033[2m"

_VERDICT_COLOR = {
    "good": _GREEN,
    "usable": _GREEN,
    "limited": _YELLOW,
    "poor": _RED,
}


def _c(text: str, color: str) -> str:
    """Apply ANSI color if stdout is a tty."""
    if sys.stdout.isatty():
        return f"{color}{text}{_RESET}"
    return text


def _header(text: str) -> None:
    print(_c(f"\n{'━' * 60}", _CYAN))
    print(_c(f"  {text}", _BOLD))
    print(_c(f"{'━' * 60}", _CYAN))


def _field(label: str, value: str, color: str = "") -> None:
    label_fmt = _c(f"  {label:<30}", _DIM)
    val_fmt = _c(str(value), color) if color else str(value)
    print(f"{label_fmt}{val_fmt}")


def _pct_color(pct: float) -> str:
    if pct >= 0.90:
        return _GREEN
    if pct >= 0.70:
        return _YELLOW
    return _RED


def _print_report(report: ProviderTestReport, show_samples: bool) -> None:
    _header("Provider Test Report")
    _field("Tested at", report.tested_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
    _field("Elapsed", f"{report.elapsed_ms:,} ms")
    _field("Provider type", report.provider_type)
    _field("Market data mode", report.market_data_mode)
    _field("Tenant", report.tenant_id)
    _field("Config", report.config_id)

    _header("Effective Config (no credentials)")
    for k, v in report.config_effective.items():
        _field(k, str(v))

    _header("Summary")
    _field("Symbols tested", str(len(report.symbols_requested)))
    _field("Symbols with data", str(report.symbols_with_data))
    _field("Symbols empty", str(report.symbols_empty))
    _field("Symbols errored", str(report.symbols_errored))
    _field("Total contracts returned", f"{report.total_contracts_returned:,}")
    _field("Quality passed", f"{report.total_contracts_quality_passed:,}")
    _field("Avg contracts/symbol", f"{report.avg_contracts_per_symbol:.1f}")
    _field(
        "Usable bid/ask",
        f"{report.pct_usable_bid_ask:.0%}",
        _pct_color(report.pct_usable_bid_ask),
    )
    _field(
        "Usable volume",
        f"{report.pct_usable_volume:.0%}",
        _pct_color(report.pct_usable_volume),
    )
    _field(
        "Usable open interest",
        f"{report.pct_usable_oi:.0%}",
        _pct_color(report.pct_usable_oi),
    )
    _field(
        "Usable implied vol",
        f"{report.pct_usable_iv:.0%}",
        _pct_color(report.pct_usable_iv),
    )

    verdict_color = _VERDICT_COLOR.get(report.quality_verdict, "")
    _field("Quality verdict", report.quality_verdict.upper(), verdict_color)

    if report.quality_notes:
        print(_c("\n  Notes:", _DIM))
        for note in report.quality_notes:
            print(f"    • {note}")

    _header("Per-symbol breakdown")
    for s in report.per_symbol:
        _print_symbol(s, show_samples)

    print()


def _print_symbol(s: SymbolDiagnostics, show_samples: bool) -> None:
    status_color = _GREEN if s.status == "ok" else (_RED if s.status == "error" else _YELLOW)
    print(f"\n  {_c(s.symbol, _BOLD)}  [{_c(s.status.upper(), status_color)}]  {s.elapsed_ms:,} ms")

    if s.status == "error":
        print(f"    {_c('Error: ' + (s.error_detail or ''), _RED)}")
        return
    if s.status == "empty":
        print(f"    {_c(s.empty_reason or 'No data returned.', _YELLOW)}")
        return

    _field("  Contracts returned", str(s.contracts_returned))
    _field("  Quality passed", str(s.contracts_quality_passed))
    _field("  Missing volume", f"{s.missing_volume} / {s.contracts_returned}")
    _field("  Missing OI", f"{s.missing_open_interest} / {s.contracts_returned}")
    _field("  Missing IV", f"{s.missing_iv} / {s.contracts_returned}")
    _field("  Missing bid", f"{s.missing_bid} / {s.contracts_returned}")
    _field("  Missing ask", f"{s.missing_ask} / {s.contracts_returned}")

    if show_samples and s.sample_contracts:
        print(_c("    Sample contracts (highest volume):", _DIM))
        print(
            _c(
                f"    {'Symbol':<8} {'Expiry':<12} {'Strike':>8} {'Type':>4} "
                f"{'Bid':>7} {'Ask':>7} {'Last':>7} {'Vol':>8} {'OI':>8} {'IV':>7}  Flags",
                _DIM,
            )
        )
        for c in s.sample_contracts:
            iv_str = f"{c.implied_vol:.3f}" if c.implied_vol is not None else "  ---"
            flags_str = ",".join(c.data_flags) if c.data_flags else ""
            print(
                f"    {c.symbol:<8} {c.expiry:<12} {c.strike:>8.2f} {c.option_type:>4} "
                f"{c.bid:>7.4f} {c.ask:>7.4f} {c.last:>7.4f} "
                f"{c.volume:>8,} {c.open_interest:>8,} {iv_str:>7}  {flags_str}"
            )


# ---------------------------------------------------------------------------
# Main async logic
# ---------------------------------------------------------------------------

async def _main(
    tenant_id: Optional[uuid.UUID],
    config_id: Optional[uuid.UUID],
    symbols: Optional[str],
    max_symbols: int,
    show_samples: bool,
) -> int:
    """Returns exit code: 0 = success/usable, 1 = poor/limited/error."""
    async with AsyncSessionLocal() as db:
        # Resolve config
        if config_id:
            cfg = await get_provider_config_by_id(db, config_id)
            if cfg is None:
                print(_c(f"Error: provider config {config_id} not found.", _RED))
                return 1
        elif tenant_id:
            tenant = await get_tenant_by_id(db, tenant_id)
            if tenant is None:
                print(_c(f"Error: tenant {tenant_id} not found.", _RED))
                return 1
            cfg = await get_active_provider_config(db, tenant_id)
            if cfg is None:
                print(
                    _c(
                        f"Error: no active provider config for tenant {tenant_id}. "
                        "Create one via POST /api/v1/tenants/{id}/providers",
                        _RED,
                    )
                )
                return 1
        else:
            print(_c("Error: provide --tenant-id or --config-id.", _RED))
            return 1

        # Resolve symbols
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:max_symbols]
        else:
            result = await db.execute(
                select(ScannerUniverse.symbol)
                .where(ScannerUniverse.tenant_id == cfg.tenant_id)
                .where(ScannerUniverse.enabled == True)
                .order_by(ScannerUniverse.priority.desc(), ScannerUniverse.created_at.asc())
                .limit(max_symbols)
            )
            symbol_list = list(result.scalars().all())

        if not symbol_list:
            print(
                _c(
                    "No symbols to test. Pass --symbols SPY,QQQ or add symbols to the universe.",
                    _YELLOW,
                )
            )
            return 1

        print(
            _c(
                f"\nRunning diagnostic for provider '{cfg.provider_type}' "
                f"on symbols: {', '.join(symbol_list)} …",
                _CYAN,
            )
        )
        print(_c("(This may take 30–60 s per symbol for IBKR)", _DIM))

        report = await run_provider_test(config=cfg, symbols=symbol_list)

    _print_report(report, show_samples)

    return 0 if report.quality_verdict in ("good", "usable") else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a provider config with a diagnostic test fetch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        help="UUID of the tenant to test (uses its default provider config).",
    )
    parser.add_argument(
        "--config-id",
        type=uuid.UUID,
        help="UUID of a specific provider config to test directly.",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma-separated symbols, e.g. SPY,QQQ",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=2,
        help="Max symbols from universe when --symbols is not given (default: 2).",
    )
    parser.add_argument(
        "--no-samples",
        action="store_true",
        help="Suppress the sample contract table.",
    )

    args = parser.parse_args()

    if not args.tenant_id and not args.config_id:
        parser.error("Provide --tenant-id or --config-id.")

    exit_code = asyncio.run(
        _main(
            tenant_id=args.tenant_id,
            config_id=args.config_id,
            symbols=args.symbols,
            max_symbols=args.max_symbols,
            show_samples=not args.no_samples,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
