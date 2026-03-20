#!/usr/bin/env python3
"""
End-to-end diagnostic for the event catalyst system.

Checks every layer in the pipeline and prints a clear pass/fail for each.
Run with the backend NOT necessarily running — hits the DB directly.

Usage:
    python scripts/check_events.py
    python scripts/check_events.py --api-url http://localhost:8000

Exit code: 0 = all checks passed, 1 = one or more checks failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import os
from pathlib import Path

# Allow running from repo root or from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    import urllib.request
    import urllib.error
    _HAS_HTTPX = False


# ── ANSI colours ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")
    FAILURES.append(msg)

def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}")

def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")

FAILURES: list[str] = []


# ── HTTP helper ───────────────────────────────────────────────────────────────

def get(url: str) -> dict:
    if _HAS_HTTPX:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    else:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())


# ── Checks ────────────────────────────────────────────────────────────────────

def check_migration(api: str) -> None:
    section("1. Migration 009 — symbol_events table")
    try:
        data = get(f"{api}/api/v1/events?limit=1")
        if data.get("success"):
            ok("GET /events returned success — table exists and router works")
        else:
            fail(f"GET /events returned success=false: {data.get('error')}")
    except Exception as exc:
        fail(
            f"GET /events failed: {exc}\n"
            "    → Run: alembic upgrade head  (from the backend/ directory)"
        )


def check_seed(api: str) -> None:
    section("2. Seed data — events in symbol_events")
    try:
        data = get(f"{api}/api/v1/events?limit=200")
        events = data.get("data") or []
        total = len(events)
        if total == 0:
            fail(
                "No events found in symbol_events.\n"
                "    → Run: python scripts/seed_events.py\n"
                "    → Or:  curl -X POST http://localhost:8000/api/v1/jobs/sync-earnings"
            )
        else:
            ok(f"{total} events in symbol_events")
            # Show upcoming
            from datetime import date
            today = date.today().isoformat()
            upcoming = [e for e in events if e.get("event_date", "") >= today]
            ok(f"  {len(upcoming)} upcoming (event_date >= today)")
            if upcoming:
                for e in upcoming[:5]:
                    print(f"     {e['symbol']:6s}  {e['event_date']}  {e['event_type']}")
                if len(upcoming) > 5:
                    print(f"     … and {len(upcoming)-5} more")
    except Exception as exc:
        fail(f"Could not reach /events: {exc}")


def check_upcoming(api: str) -> None:
    section("3. /events/upcoming — resolver + universe join")
    try:
        data = get(f"{api}/api/v1/events/upcoming")
        results = data.get("data") or []
        if not results:
            warn(
                "No upcoming events returned.\n"
                "    Possible causes:\n"
                "      a) No events seeded (see check 2)\n"
                "      b) Scanner universe is empty (add symbols via /universe)\n"
                "      c) Events exist but for symbols not in the universe\n"
                "      d) All events are in the past"
            )
        else:
            ok(f"{len(results)} upcoming events resolved for universe symbols")
            for e in results[:5]:
                print(f"     {e['symbol']:6s}  {e['event_date']}  {e['catalyst_context']}")
    except Exception as exc:
        fail(f"Could not reach /events/upcoming: {exc}")


def check_alert_enrichment(api: str) -> None:
    section("4. Alert enrichment — catalyst_context on alerts")
    try:
        # Get recent alerts
        data = get(f"{api}/api/v1/alerts?limit=50&status=active")
        alerts = data.get("data") or []
        if not alerts:
            warn("No active alerts to inspect.  Run a signal job first.")
            return

        enriched = [a for a in alerts if a.get("catalyst_context")]
        total = len(alerts)
        pct = round(100 * len(enriched) / total) if total else 0

        if enriched:
            ok(f"{len(enriched)}/{total} active alerts have catalyst_context ({pct}%)")
            sample = enriched[0]
            ok(f"  Sample: [{sample['underlying_symbol']}] {sample['catalyst_context']}")
        else:
            warn(
                f"0/{total} active alerts have catalyst_context.\n"
                "    Possible causes:\n"
                "      a) Alerts were created before events were seeded\n"
                "         → Run: POST /api/v1/events/backfill-alerts  (backfills NULLs)\n"
                "      b) Events exist but signal engine hasn't re-run\n"
                "         → Run a new signal/ingestion job\n"
                "      c) Events are seeded for different symbols than active alerts"
            )
    except Exception as exc:
        fail(f"Could not reach /alerts: {exc}")


def check_alert_detail(api: str) -> None:
    section("5. Alert detail — catalyst fields in AlertOut")
    try:
        # Get one alert id
        data = get(f"{api}/api/v1/alerts?limit=1&status=active")
        alerts = data.get("data") or []
        if not alerts:
            warn("No active alerts — skipping detail check")
            return

        alert_id = alerts[0]["id"]
        detail = get(f"{api}/api/v1/alerts/{alert_id}")
        a = detail.get("data") or {}

        missing = [f for f in ("catalyst_context", "days_to_event", "next_event_type", "next_event_date") if f not in a]
        if missing:
            fail(f"Fields missing from AlertOut response: {missing}")
        else:
            ok("All 4 catalyst fields present in AlertOut")
            if a.get("catalyst_context"):
                ok(f"  catalyst_context = {a['catalyst_context']!r}")
            else:
                warn("  catalyst_context is null on this alert (see check 4)")
    except Exception as exc:
        fail(f"Could not reach /alerts/{{id}}: {exc}")


def check_yfinance() -> None:
    section("6. yfinance availability (for sync-earnings job)")
    try:
        import yfinance
        ok(f"yfinance {yfinance.__version__} installed")
        # Quick smoke test
        ticker = yfinance.Ticker("AAPL")
        cal = ticker.calendar
        if cal and "Earnings Date" in cal:
            ok("  AAPL calendar fetch succeeded")
        else:
            warn("  AAPL calendar returned no Earnings Date — Yahoo Finance may be rate-limiting")
    except ImportError:
        warn(
            "yfinance not installed — sync-earnings job will fail\n"
            "    → Run: pip install yfinance>=0.2.38"
        )
    except Exception as exc:
        warn(f"yfinance installed but calendar fetch failed: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Check event catalyst pipeline")
    parser.add_argument("--api-url", default="http://localhost:8000", dest="api")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    print(f"\n{BOLD}Event Catalyst Diagnostic{RESET}  →  {api}")
    print("─" * 60)

    check_migration(api)
    check_seed(api)
    check_upcoming(api)
    check_alert_enrichment(api)
    check_alert_detail(api)
    check_yfinance()

    print("\n" + "─" * 60)
    if FAILURES:
        print(f"{RED}{BOLD}FAILED{RESET}: {len(FAILURES)} check(s) failed")
        for f in FAILURES:
            print(f"  · {f}")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}ALL CHECKS PASSED{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
