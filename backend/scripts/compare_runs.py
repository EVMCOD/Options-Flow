#!/usr/bin/env python3
"""
Run comparison CLI.

Connects directly to the database (no API server needed), fetches recent
successful runs, and prints a side-by-side comparison table showing:
  - ingestion metrics (records, symbols)
  - signal engine filter breakdown
  - alert distribution
  - quality stats

Use this after adjusting thresholds to see if the scanner improved.

Usage:
    cd backend/
    python scripts/compare_runs.py
    python scripts/compare_runs.py --limit 10
    python scripts/compare_runs.py --tenant-id 00000000-0000-0000-0000-000000000001
    python scripts/compare_runs.py --limit 5 --no-thresholds
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.logging_setup import configure_logging
from app.models.models import IngestionRun
from app.schemas.schemas import RunCompareEntry, RunSignalSummary

configure_logging()

_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_DIM = "\033[2m"


def _c(text: str, color: str) -> str:
    if sys.stdout.isatty():
        return f"{color}{text}{_RESET}"
    return text


def _pct(n: int, total: int) -> str:
    if total == 0:
        return "  —"
    return f"{n / total:.0%}"


def _bar(rate: float, width: int = 10) -> str:
    filled = round(rate * width)
    return "█" * filled + "░" * (width - filled)


def _rate_color(rate: float, high: float = 0.35, low: float = 0.02) -> str:
    if rate > high:
        return _RED
    if rate < low:
        return _DIM
    return _GREEN


def _print_run_header(entry: RunCompareEntry) -> None:
    started = entry.started_at.strftime("%m-%d %H:%M")
    provider = entry.provider_type or "?"
    mode = entry.market_data_mode or "?"
    print(
        _c(f"\n{'─' * 60}", _DIM)
    )
    print(
        _c(f"  Run {str(entry.id)[:8]}…  {started}  [{provider} / {mode}]", _BOLD)
    )
    print(
        f"  Status: {_c(entry.status, _GREEN if entry.status == 'success' else _RED)}"
        f"  Records ingested: {entry.records_ingested:,}"
    )


def _print_signal_summary(s: RunSignalSummary) -> None:
    total = s.snapshots_above_min_volume
    passed = s.passed_prefilters

    print(_c("  Ingestion filter pipeline:", _DIM))
    print(f"    Snapshots ≥ MIN_VOLUME : {total:>6,}")

    filters = [
        ("zero_price",  s.filtered.zero_price),
        ("far_expiry",  s.filtered.far_expiry),
        ("deep_otm",    s.filtered.deep_otm),
        ("low_premium", s.filtered.low_premium),
        ("low_oi",      s.filtered.low_oi),
    ]
    for name, count in filters:
        rate = count / total if total > 0 else 0.0
        color = _rate_color(rate)
        bar = _bar(rate)
        pct = _pct(count, total)
        print(
            f"    − {name:<14} : {count:>5,}  {_c(pct, color)}  {_c(bar, color)}"
        )

    print(f"    Passed pre-filters     : {passed:>6,}  {_pct(passed, total)}")

    print(_c("  Signal engine output:", _DIM))
    print(f"    Features created       : {s.features_created:>6,}  {_pct(s.features_created, passed)}")
    print(f"    Quality penalized      : {s.quality_penalized:>6,}  {_pct(s.quality_penalized, s.features_created)}")
    print(f"    Insufficient baseline  : {s.insufficient_baseline:>6,}  {_pct(s.insufficient_baseline, passed)}")
    print(f"    Alerts created         : {s.alerts_created:>6,}  {_pct(s.alerts_created, s.features_created)}")
    print(f"    Avg anomaly score      : {s.avg_anomaly_score:>6.2f} / 10.00")

    dist = s.alert_distribution
    total_alerts = sum([dist.LOW, dist.MEDIUM, dist.HIGH, dist.CRITICAL])
    if total_alerts > 0:
        print(
            f"    Alert levels           : "
            f"{_c(f'LOW={dist.LOW}', _DIM)}  "
            f"{_c(f'MED={dist.MEDIUM}', _YELLOW)}  "
            f"{_c(f'HIGH={dist.HIGH}', _RED)}  "
            f"{_c(f'CRIT={dist.CRITICAL}', _RED + _BOLD)}"
        )

    if s.top_symbols:
        print(_c("  Top symbols:", _DIM))
        for sym in s.top_symbols[:5]:
            alert_str = f"  {_c(str(sym.alerts) + ' alerts', _YELLOW)}" if sym.alerts else ""
            print(
                f"    {sym.symbol:<6}  {sym.contracts_evaluated:>4} contracts"
                f"  {sym.features:>4} features{alert_str}"
            )


def _print_thresholds(s: RunSignalSummary) -> None:
    if not s.thresholds_applied:
        return
    print(_c("  Thresholds applied:", _DIM))
    for k, v in s.thresholds_applied.items():
        print(f"    {k:<35} {v}")


def _print_no_summary(entry: RunCompareEntry) -> None:
    print(_c("  ⚠  No signal_summary_json — run before migration 005.", _YELLOW))


async def _main(
    tenant_id: Optional[uuid.UUID],
    limit: int,
    show_thresholds: bool,
) -> int:
    async with AsyncSessionLocal() as db:
        effective = tenant_id or uuid.UUID(settings.DEFAULT_TENANT_ID)

        result = await db.execute(
            select(IngestionRun)
            .where(IngestionRun.tenant_id == effective)
            .where(IngestionRun.status == "success")
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
        )
        runs = list(result.scalars().all())

    if not runs:
        print(_c("No successful runs found.", _YELLOW))
        return 1

    print(_c(f"\n{'━' * 60}", _CYAN))
    print(_c(f"  Run Comparison  ({len(runs)} most-recent successful runs)", _BOLD))
    print(_c(f"{'━' * 60}", _CYAN))

    for r in runs:
        summary = RunSignalSummary.from_json(r.signal_summary_json)
        entry = RunCompareEntry(
            id=r.id,
            started_at=r.started_at,
            finished_at=r.finished_at,
            status=r.status,
            provider_type=r.provider_type,
            market_data_mode=r.market_data_mode,
            records_ingested=r.records_ingested,
            signal_summary=summary,
        )
        _print_run_header(entry)
        if summary is None:
            _print_no_summary(entry)
        else:
            _print_signal_summary(summary)
            if show_thresholds:
                _print_thresholds(summary)

    print(_c(f"\n{'━' * 60}\n", _CYAN))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare recent scanner runs side-by-side.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        help="Tenant UUID (defaults to DEFAULT_TENANT_ID from config).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of most-recent runs to compare (default: 5).",
    )
    parser.add_argument(
        "--no-thresholds",
        action="store_true",
        help="Suppress the threshold snapshot table.",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(
        _main(
            tenant_id=args.tenant_id,
            limit=args.limit,
            show_thresholds=not args.no_thresholds,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
