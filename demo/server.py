"""
Options Flow Radar — Demo API Server

Standalone FastAPI server that serves curated fixture data.
Zero database. Zero scanner. No API keys. No providers.

Architecture
────────────
· All data is computed once on startup from _build_*() functions.
· Dates are computed dynamically from date.today() so the demo stays
  current across restarts — "Earnings in 6 days" always means 6 days
  from the moment the server starts.
· Write operations (POST/PATCH/DELETE) succeed in-memory but reset on
  restart. This lets you interact with forms without errors.
· Every response is wrapped in {"success": true, "data": ..., "error": null}
  matching the real backend's ApiResponse<T> contract exactly.

Deploying on Render
───────────────────
1. Create a new Web Service, set Root Directory: demo
2. Build: pip install -r requirements.txt
3. Start:  uvicorn server:app --host 0.0.0.0 --port $PORT
4. Set NEXT_PUBLIC_API_URL on your frontend service to this service's URL.

Running locally
───────────────
  cd demo
  pip install -r requirements.txt
  uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Options Flow Radar — Demo API",
    description="Curated demo data. Serves the full API contract. In-memory writes reset on restart.",
    version="demo",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _date(offset_days: int) -> str:
    """ISO date string N days from today."""
    return (date.today() + timedelta(days=offset_days)).isoformat()


def _dt(hours_ago: float = 0.0) -> str:
    """ISO datetime string N hours before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ok(data: Any) -> dict:
    return {"success": True, "data": data, "error": None}


# ── Universe ──────────────────────────────────────────────────────────────────

def _build_universe() -> List[dict]:
    symbols = [
        ("SPY", 10), ("QQQ", 9), ("AAPL", 8), ("NVDA", 8),
        ("TSLA", 7), ("MSFT", 7), ("AMD", 6), ("META", 6),
    ]
    created = _dt(72)
    return [
        {
            "id": f"u{i:07d}-0000-0000-0000-{_TENANT_ID[-12:]}",
            "tenant_id": _TENANT_ID,
            "symbol": sym,
            "enabled": True,
            "priority": pri,
            "created_at": created,
        }
        for i, (sym, pri) in enumerate(symbols, start=1)
    ]


# ── Event schedule ────────────────────────────────────────────────────────────
#
# Each entry: (id_suffix, symbol, event_type, title, days_from_today, event_time, source, notes)
#
_EVENT_SCHEDULE = [
    ("e001", "SPY",  "macro_relevant", "FOMC Rate Decision",          5,  "after_market", "manual",
     "Federal Reserve FOMC meeting — rate decision and press conference. High-impact macro event."),
    ("e002", "QQQ",  "macro_relevant", "FOMC Rate Decision",          5,  "after_market", "manual",
     "QQQ tracks NASDAQ-100; high sensitivity to rate decision and forward guidance."),
    ("e003", "NVDA", "earnings",       "NVDA Q1 FY2027 Earnings",     6,  "AMC",          "yfinance",
     "Q1 FY2027 earnings. Analyst consensus: EPS $0.88, Revenue $24.1B. Data center GPU segment in focus."),
    ("e004", "TSLA", "earnings",       "TSLA Q1 2027 Earnings",       7,  "AMC",          "yfinance",
     "Q1 2027 earnings. Deliveries already reported; focus on margins, FSD revenue recognition, and Optimus update."),
    ("e005", "AAPL", "earnings",       "AAPL Q2 FY2027 Earnings",     14, "AMC",          "yfinance",
     "Q2 FY2027 earnings. iPhone replacement cycle and Apple Intelligence monetization in focus."),
    ("e006", "META", "earnings",       "META Q1 2027 Earnings",       21, "AMC",          "yfinance",
     "Q1 2027 earnings. Advertising revenue growth, AI capex guidance, and Llama 4 update expected."),
    ("e007", "AMD",  "earnings",       "AMD Q1 2027 Earnings",        39, "AMC",          "yfinance",
     "Q1 2027 earnings. Data center GPU MI-series ramp vs NVDA competition."),
    ("e008", "MSFT", "earnings",       "MSFT Q3 FY2027 Earnings",     40, "AMC",          "yfinance",
     "Q3 FY2027 earnings. Azure growth rate and Copilot seat expansion."),
]


def _build_events() -> List[dict]:
    now = _now()
    events = []
    for sfx, sym, etype, title, offset, etime, source, notes in _EVENT_SCHEDULE:
        events.append({
            "id": f"{sfx}0000-0000-0000-0000-000000000001",
            "tenant_id": None,
            "symbol": sym,
            "event_type": etype,
            "title": title,
            "event_date": _date(offset),
            "event_time": etime,
            "source": source,
            "notes": notes,
            "created_at": now,
            "updated_at": now,
        })
    return events


def _build_upcoming(days_window: int = 30) -> List[dict]:
    upcoming = []
    for _, sym, etype, title, offset, _, _, _ in _EVENT_SCHEDULE:
        if offset > days_window:
            continue
        is_near = offset <= 7
        if etype == "earnings":
            context = f"Earnings in {offset} day{'s' if offset != 1 else ''} (AMC)"
        elif etype == "macro_relevant":
            context = f"FOMC meeting in {offset} day{'s' if offset != 1 else ''}"
        else:
            context = f"{title} in {offset} days"
        upcoming.append({
            "symbol": sym,
            "event_type": etype,
            "title": title,
            "event_date": _date(offset),
            "days_to_event": offset,
            "catalyst_context": context,
            "is_near": is_near,
        })
    return upcoming


# ── Alert data ────────────────────────────────────────────────────────────────

def _cf(
    vol_ratio: float,
    baseline: int,
    current: int,
    zscore: float,
    vol_assess: str,
    notional: float,
    notional_assess: str,
    dte: int,
    dte_assess: str,
    confidence: float,
    source: str,
    quality_assess: str,
    spot: float,
    strike: float,
    iv: Optional[float] = None,
    catalyst: Optional[dict] = None,
) -> dict:
    """Build a ContributingFactors dict."""
    distance_pct = abs(spot - strike) / spot
    if distance_pct < 0.015:
        label = "near-ATM"
    elif strike > spot:
        label = f"call OTM ({distance_pct * 100:.1f}%)"
    else:
        label = f"put OTM ({distance_pct * 100:.1f}%)"

    result: dict = {
        "volume_spike": {
            "ratio": vol_ratio,
            "baseline_avg": baseline,
            "current": current,
            "zscore": zscore,
            "assessment": vol_assess,
        },
        "notional": {
            "premium_proxy_usd": notional,
            "assessment": notional_assess,
        },
        "timing": {
            "dte": dte,
            "assessment": dte_assess,
        },
        "quality": {
            "confidence": confidence,
            "flags": [],
            "data_source": source,
            "assessment": quality_assess,
        },
        "moneyness": {
            "spot": spot,
            "strike": strike,
            "distance_pct": round(distance_pct, 4),
            "label": label,
        },
        "iv": {"value": iv} if iv is not None else None,
    }
    if catalyst:
        result["catalyst"] = catalyst
    return result


def _alert(
    aid: str,
    symbol: str,
    strike: float,
    option_type: str,
    expiry_offset: int,
    alert_level: str,
    anomaly_score: float,
    raw_anomaly_score: float,
    quality_confidence: float,
    title: str,
    priority_score: float,
    status: str,
    catalyst_context: Optional[str],
    days_to_event: Optional[int],
    next_event_type: Optional[str],
    next_event_offset: Optional[int],
    pattern_tags: Optional[List[str]],
    explanation: str,
    contributing_factors: Optional[dict],
    created_hours_ago: float = 1.0,
) -> dict:
    """Build a full AlertOut-shaped dict."""
    created = _dt(created_hours_ago)
    return {
        # AlertSummary fields
        "id": aid,
        "underlying_symbol": symbol,
        "expiry": _date(expiry_offset),
        "strike": str(strike),
        "option_type": option_type,
        "as_of_ts": created,
        "alert_level": alert_level,
        "anomaly_score": anomaly_score,
        "raw_anomaly_score": raw_anomaly_score,
        "quality_confidence": quality_confidence,
        "dte_at_alert": expiry_offset,
        "title": title,
        "priority_score": priority_score,
        "status": status,
        "created_at": created,
        "catalyst_context": catalyst_context,
        "days_to_event": days_to_event,
        "pattern_tags": pattern_tags,
        # AlertOut extra fields
        "snapshot_id": f"snap-{aid[:8]}",
        "quality_flags": None,
        "explanation": explanation,
        "contributing_factors_json": contributing_factors,
        "next_event_type": next_event_type,
        "next_event_date": _date(next_event_offset) if next_event_offset is not None else None,
    }


def _build_alerts() -> List[dict]:
    return [

        # ── CRITICAL ─────────────────────────────────────────────────────────

        _alert(
            aid="a1000001-0000-0000-0000-000000000001",
            symbol="NVDA", strike=820.0, option_type="C", expiry_offset=15,
            alert_level="CRITICAL", anomaly_score=9.1, raw_anomaly_score=9.8,
            quality_confidence=0.93,
            title="NVDA: Unusual Call Sweep 820C — 10.2× Normal Vol",
            priority_score=8.9, status="active",
            catalyst_context="Earnings in 6 days (AMC)",
            days_to_event=6, next_event_type="earnings", next_event_offset=6,
            pattern_tags=["call_sweep", "repeat_strike"],
            explanation=(
                "10.2× normal volume on NVDA 820C (4,284 vs 420-contract baseline, z-score 5.2). "
                "Third consecutive session of unusual call activity at this exact strike — a "
                "repeat_strike pattern indicating sustained directional conviction. $12.0M notional "
                "confirms institutional scale. Near-ATM call (spot $812.40, strike $820) with 15 DTE "
                "— high gamma sensitivity. Catalyst: NVDA earnings in 6 days (AMC). Priority score "
                "boosted ×1.45 for earnings proximity. Rare confluence: extreme anomaly + catalyst + "
                "repeat pattern = highest-conviction signal in the universe."
            ),
            contributing_factors=_cf(
                vol_ratio=10.2, baseline=420, current=4284, zscore=5.2,
                vol_assess="Extreme — 10.2× normal. Z-score 5.2 (1-in-10M probability under random baseline). Third day of repeat activity at same strike.",
                notional=12_000_000, notional_assess="$12.0M notional — unambiguous institutional-scale positioning.",
                dte=15, dte_assess="15 DTE — front-month expiry. Earnings in 6 days fall within this window: gamma event fully captured.",
                confidence=0.93, source="ibkr_delayed",
                quality_assess="High confidence — full bid/ask, open interest, and multi-session history available.",
                spot=812.40, strike=820.0, iv=0.72,
                catalyst={
                    "event_type": "earnings", "event_date": _date(6),
                    "days_to_event": 6, "context": "Earnings in 6 days (AMC)",
                    "boost_applied": 1.45,
                },
            ),
            created_hours_ago=1.5,
        ),

        _alert(
            aid="a1000002-0000-0000-0000-000000000001",
            symbol="TSLA", strike=285.0, option_type="C", expiry_offset=28,
            alert_level="CRITICAL", anomaly_score=8.8, raw_anomaly_score=9.2,
            quality_confidence=0.89,
            title="TSLA: Block Trade 285C — 7.8× Normal Vol",
            priority_score=8.4, status="active",
            catalyst_context="Earnings in 7 days (AMC)",
            days_to_event=7, next_event_type="earnings", next_event_offset=7,
            pattern_tags=["block_trade", "call_sweep"],
            explanation=(
                "7.8× normal volume on TSLA 285C via single large block (6,180 contracts, z-score 4.8). "
                "$7.4M notional — clearly institutional. Strike 3.6% OTM (spot $274.80): consistent "
                "with upside directional conviction, not a hedge. 28 DTE gives time to capture "
                "earnings reaction plus post-event drift. TSLA earnings in 7 days (AMC) — Q1 "
                "deliveries already reported; options market pricing in an above-consensus margin "
                "or FSD monetization surprise."
            ),
            contributing_factors=_cf(
                vol_ratio=7.8, baseline=792, current=6180, zscore=4.8,
                vol_assess="Very high — 7.8× normal. Single clean block — no fragmentation across venues.",
                notional=7_400_000, notional_assess="$7.4M in single block. Institutional signature.",
                dte=28, dte_assess="28 DTE — first monthly expiry after earnings. Optimal structure for earnings capture.",
                confidence=0.89, source="ibkr_delayed",
                quality_assess="High confidence. Block trade identifiable from time-and-sales.",
                spot=274.80, strike=285.0, iv=0.81,
                catalyst={
                    "event_type": "earnings", "event_date": _date(7),
                    "days_to_event": 7, "context": "Earnings in 7 days (AMC)",
                    "boost_applied": 1.42,
                },
            ),
            created_hours_ago=2.2,
        ),

        # ── HIGH ─────────────────────────────────────────────────────────────

        _alert(
            aid="a1000003-0000-0000-0000-000000000001",
            symbol="SPY", strike=560.0, option_type="P", expiry_offset=8,
            alert_level="HIGH", anomaly_score=7.8, raw_anomaly_score=8.2,
            quality_confidence=0.88,
            title="SPY: Put Buying Surge 560P — 6.1× Normal Vol",
            priority_score=7.6, status="active",
            catalyst_context="FOMC meeting in 5 days",
            days_to_event=5, next_event_type="macro_relevant", next_event_offset=5,
            pattern_tags=["put_sweep", "volume_acceleration"],
            explanation=(
                "6.1× normal volume on SPY 560P (25,620 vs 4,200-contract baseline, z-score 4.0). "
                "Volume has been accelerating across 3 consecutive sessions — systematic hedge "
                "accumulation pattern. $12.3M notional. Strike 0.9% OTM (spot $565.20): near-ATM "
                "protective put. FOMC meeting in 5 days — consistent with institutional downside "
                "protection ahead of rate decision. Corroborated by simultaneous QQQ 475P activity."
            ),
            contributing_factors=_cf(
                vol_ratio=6.1, baseline=4200, current=25620, zscore=4.0,
                vol_assess="High — 6.1× normal. 3-session volume_acceleration pattern detected.",
                notional=12_300_000, notional_assess="$12.3M notional — systematic program-level hedging.",
                dte=8, dte_assess="8 DTE — tight expiry spanning FOMC date. Classic rate-event hedge structure.",
                confidence=0.88, source="ibkr_delayed",
                quality_assess="High confidence. High-volume liquid contract, tight spreads.",
                spot=565.20, strike=560.0, iv=0.18,
                catalyst={
                    "event_type": "macro_relevant", "event_date": _date(5),
                    "days_to_event": 5, "context": "FOMC meeting in 5 days",
                    "boost_applied": 1.28,
                },
            ),
            created_hours_ago=1.1,
        ),

        _alert(
            aid="a1000004-0000-0000-0000-000000000001",
            symbol="AAPL", strike=230.0, option_type="C", expiry_offset=28,
            alert_level="HIGH", anomaly_score=7.2, raw_anomaly_score=7.6,
            quality_confidence=0.91,
            title="AAPL: Unusual Call Activity 230C — 5.3× Normal Vol",
            priority_score=7.1, status="active",
            catalyst_context="Earnings in 14 days (AMC)",
            days_to_event=14, next_event_type="earnings", next_event_offset=14,
            pattern_tags=["call_sweep"],
            explanation=(
                "5.3× normal volume on AAPL 230C (8,900 vs 1,679-contract baseline, z-score 3.7). "
                "$2.85M notional. Strike 5.5% OTM (spot $217.90) — upside directional positioning. "
                "AAPL earnings in 14 days (AMC). Call buyers establishing position ahead of Q2 "
                "FY2027 print. iPhone replacement cycle and Apple Intelligence monetization in focus."
            ),
            contributing_factors=_cf(
                vol_ratio=5.3, baseline=1679, current=8900, zscore=3.7,
                vol_assess="High — 5.3× normal. Clean directional call sweep, no counter-put activity.",
                notional=2_850_000, notional_assess="$2.85M notional — significant institutional position.",
                dte=28, dte_assess="28 DTE — spans next earnings cycle. Structured for event capture.",
                confidence=0.91, source="ibkr_delayed",
                quality_assess="High confidence. Liquid contract, tight spreads.",
                spot=217.90, strike=230.0, iv=0.31,
                catalyst={
                    "event_type": "earnings", "event_date": _date(14),
                    "days_to_event": 14, "context": "Earnings in 14 days (AMC)",
                    "boost_applied": 1.22,
                },
            ),
            created_hours_ago=3.4,
        ),

        _alert(
            aid="a1000005-0000-0000-0000-000000000001",
            symbol="META", strike=700.0, option_type="C", expiry_offset=42,
            alert_level="HIGH", anomaly_score=7.0, raw_anomaly_score=7.4,
            quality_confidence=0.87,
            title="META: Large Block 700C — 4.9× Normal Vol",
            priority_score=6.8, status="active",
            catalyst_context="Earnings in 21 days (AMC)",
            days_to_event=21, next_event_type="earnings", next_event_offset=21,
            pattern_tags=["block_trade"],
            explanation=(
                "4.9× normal volume on META 700C via single large block (3,200 contracts, z-score 3.5). "
                "$5.76M notional — clearly institutional. Strike 4.5% OTM (spot $669.80): OTM call "
                "selection indicates high-conviction upside bet, not a hedge. 42 DTE — structured to "
                "capture earnings reaction and post-event drift. META earnings in 21 days (AMC); "
                "ad revenue growth and AI capex guidance expected."
            ),
            contributing_factors=_cf(
                vol_ratio=4.9, baseline=653, current=3200, zscore=3.5,
                vol_assess="High — 4.9× normal. Single clean block — unambiguous directional intent.",
                notional=5_760_000, notional_assess="$5.76M in single print — high-conviction institutional bet.",
                dte=42, dte_assess="42 DTE — two monthlies. Long structure for earnings capture + drift.",
                confidence=0.87, source="ibkr_delayed",
                quality_assess="High confidence. Clean block identifiable in time-and-sales.",
                spot=669.80, strike=700.0, iv=0.42,
                catalyst={
                    "event_type": "earnings", "event_date": _date(21),
                    "days_to_event": 21, "context": "Earnings in 21 days (AMC)",
                    "boost_applied": 1.15,
                },
            ),
            created_hours_ago=4.8,
        ),

        _alert(
            aid="a1000006-0000-0000-0000-000000000001",
            symbol="AMD", strike=135.0, option_type="C", expiry_offset=42,
            alert_level="HIGH", anomaly_score=7.1, raw_anomaly_score=7.5,
            quality_confidence=0.86,
            title="AMD: Call Sweep 135C — 4.4× Normal Vol",
            priority_score=6.3, status="active",
            catalyst_context=None, days_to_event=None,
            next_event_type=None, next_event_offset=None,
            pattern_tags=["call_sweep", "cross_exchange"],
            explanation=(
                "4.4× normal volume on AMD 135C (4,600 vs 1,046-contract baseline, z-score 3.2). "
                "$2.2M notional. Strike 3.8% OTM (spot $130.10). Cross-exchange sweep executed "
                "across 4 venues — systematic institutional execution pattern. No immediate catalyst "
                "identified; priority score reflects anomaly strength and notional alone."
            ),
            contributing_factors=_cf(
                vol_ratio=4.4, baseline=1046, current=4600, zscore=3.2,
                vol_assess="High — 4.4× normal. Multi-venue sweep execution pattern detected.",
                notional=2_200_000, notional_assess="$2.2M notional. Meaningful size for AMD.",
                dte=42, dte_assess="42 DTE — no near-term catalyst. Long structure.",
                confidence=0.86, source="ibkr_delayed",
                quality_assess="Good confidence. Cross-exchange activity confirms genuine interest.",
                spot=130.10, strike=135.0, iv=0.55,
            ),
            created_hours_ago=5.2,
        ),

        # ── MEDIUM ───────────────────────────────────────────────────────────

        _alert(
            aid="a1000007-0000-0000-0000-000000000001",
            symbol="QQQ", strike=475.0, option_type="P", expiry_offset=8,
            alert_level="MEDIUM", anomaly_score=5.8, raw_anomaly_score=6.0,
            quality_confidence=0.85,
            title="QQQ: Put Accumulation 475P — 3.2× Normal Vol",
            priority_score=5.4, status="active",
            catalyst_context="FOMC meeting in 5 days",
            days_to_event=5, next_event_type="macro_relevant", next_event_offset=5,
            pattern_tags=["put_sweep"],
            explanation=(
                "3.2× normal volume on QQQ 475P (14,200 contracts, z-score 2.9). $4.8M notional. "
                "Corroborates SPY 560P activity — consistent with systematic macro hedging across "
                "index ETFs ahead of FOMC. QQQ has higher rate sensitivity than SPY."
            ),
            contributing_factors=None, created_hours_ago=1.2,
        ),

        _alert(
            aid="a1000008-0000-0000-0000-000000000001",
            symbol="MSFT", strike=430.0, option_type="C", expiry_offset=28,
            alert_level="MEDIUM", anomaly_score=5.5, raw_anomaly_score=5.7,
            quality_confidence=0.84,
            title="MSFT: Call Activity 430C — 3.0× Normal Vol",
            priority_score=5.1, status="active",
            catalyst_context=None, days_to_event=None,
            next_event_type=None, next_event_offset=None,
            pattern_tags=None,
            explanation=(
                "3.0× normal volume on MSFT 430C (3,980 contracts, z-score 2.7). $2.7M notional. "
                "Strike 3.6% OTM (spot $415.20). No imminent catalyst. Monitoring for follow-through."
            ),
            contributing_factors=None, created_hours_ago=6.1,
        ),

        _alert(
            aid="a1000009-0000-0000-0000-000000000001",
            symbol="NVDA", strike=780.0, option_type="P", expiry_offset=15,
            alert_level="MEDIUM", anomaly_score=5.2, raw_anomaly_score=5.5,
            quality_confidence=0.90,
            title="NVDA: Protective Put Activity 780P — 2.8× Normal Vol",
            priority_score=4.8, status="active",
            catalyst_context="Earnings in 6 days (AMC)",
            days_to_event=6, next_event_type="earnings", next_event_offset=6,
            pattern_tags=None,
            explanation=(
                "2.8× normal volume on NVDA 780P (2,850 contracts, z-score 2.5). $6.3M notional. "
                "Concurrent with NVDA 820C call sweep (CRITICAL, A1): the options market is showing "
                "both aggressive upside conviction AND downside protection in NVDA ahead of earnings "
                "in 6 days. Classic pre-earnings strangle build-out — someone is positioning for a "
                "large move in either direction."
            ),
            contributing_factors=None, created_hours_ago=1.8,
        ),

        _alert(
            aid="a100000a-0000-0000-0000-000000000001",
            symbol="AAPL", strike=210.0, option_type="P", expiry_offset=7,
            alert_level="MEDIUM", anomaly_score=5.0, raw_anomaly_score=5.2,
            quality_confidence=0.88,
            title="AAPL: Put Hedge 210P — 2.6× Normal Vol",
            priority_score=4.5, status="active",
            catalyst_context="Earnings in 14 days (AMC)",
            days_to_event=14, next_event_type="earnings", next_event_offset=14,
            pattern_tags=None,
            explanation=(
                "2.6× normal volume on AAPL 210P (5,800 contracts, z-score 2.3). $696K notional. "
                "Short-dated (7 DTE) — expires before earnings. Near-term hedge or speculative "
                "downside bet. AAPL earnings in 14 days."
            ),
            contributing_factors=None, created_hours_ago=3.9,
        ),

        _alert(
            aid="a100000b-0000-0000-0000-000000000001",
            symbol="AMD", strike=125.0, option_type="P", expiry_offset=5,
            alert_level="MEDIUM", anomaly_score=5.1, raw_anomaly_score=5.3,
            quality_confidence=0.83,
            title="AMD: Put Activity 125P — 2.4× Normal Vol",
            priority_score=4.2, status="active",
            catalyst_context=None, days_to_event=None,
            next_event_type=None, next_event_offset=None,
            pattern_tags=None,
            explanation=(
                "2.4× normal volume on AMD 125P (2,100 contracts, z-score 2.1). $588K notional. "
                "Short-dated near-ATM put (spot $130.10, strike $125). No catalyst identified."
            ),
            contributing_factors=None, created_hours_ago=4.2,
        ),

        # ── LOW ──────────────────────────────────────────────────────────────

        _alert(
            aid="a100000c-0000-0000-0000-000000000001",
            symbol="META", strike=660.0, option_type="P", expiry_offset=14,
            alert_level="LOW", anomaly_score=4.2, raw_anomaly_score=4.4,
            quality_confidence=0.82,
            title="META: Put Flow 660P — 2.2× Normal Vol",
            priority_score=3.8, status="acknowledged",
            catalyst_context=None, days_to_event=None,
            next_event_type=None, next_event_offset=None,
            pattern_tags=None,
            explanation="2.2× normal volume on META 660P. Moderate put activity, below action threshold. Acknowledged.",
            contributing_factors=None, created_hours_ago=22.0,
        ),

        _alert(
            aid="a100000d-0000-0000-0000-000000000001",
            symbol="MSFT", strike=410.0, option_type="P", expiry_offset=5,
            alert_level="LOW", anomaly_score=3.8, raw_anomaly_score=4.0,
            quality_confidence=0.81,
            title="MSFT: Light Put Activity 410P — 2.0× Normal Vol",
            priority_score=3.4, status="dismissed",
            catalyst_context=None, days_to_event=None,
            next_event_type=None, next_event_offset=None,
            pattern_tags=None,
            explanation="2.0× normal volume on MSFT 410P. Low conviction; dismissed.",
            contributing_factors=None, created_hours_ago=23.0,
        ),

        _alert(
            aid="a100000e-0000-0000-0000-000000000001",
            symbol="TSLA", strike=265.0, option_type="P", expiry_offset=5,
            alert_level="LOW", anomaly_score=3.5, raw_anomaly_score=3.7,
            quality_confidence=0.80,
            title="TSLA: Put Activity 265P — 1.9× Normal Vol",
            priority_score=3.2, status="acknowledged",
            catalyst_context="Earnings in 7 days (AMC)",
            days_to_event=7, next_event_type="earnings", next_event_offset=7,
            pattern_tags=None,
            explanation=(
                "1.9× normal volume on TSLA 265P (spot $274.80, strike $265). Near-term put activity "
                "ahead of TSLA earnings in 7 days. Minimal size — likely retail. Acknowledged."
            ),
            contributing_factors=None, created_hours_ago=18.0,
        ),

        _alert(
            aid="a100000f-0000-0000-0000-000000000001",
            symbol="SPY", strike=570.0, option_type="C", expiry_offset=8,
            alert_level="LOW", anomaly_score=3.2, raw_anomaly_score=3.4,
            quality_confidence=0.86,
            title="SPY: Light Call Activity 570C — 1.8× Normal Vol",
            priority_score=3.0, status="active",
            catalyst_context="FOMC meeting in 5 days",
            days_to_event=5, next_event_type="macro_relevant", next_event_offset=5,
            pattern_tags=None,
            explanation=(
                "1.8× normal volume on SPY 570C. Minor call activity ahead of FOMC. Contrasts with "
                "dominant put flow — may be risk-reversal component or post-FOMC upside speculation."
            ),
            contributing_factors=None, created_hours_ago=2.5,
        ),
    ]


# ── Metrics ───────────────────────────────────────────────────────────────────

def _build_metrics(alerts: List[dict]) -> dict:
    active_hc = sum(
        1 for a in alerts
        if a["status"] == "active" and a["alert_level"] in ("HIGH", "CRITICAL")
    )
    by_level: Dict[str, int] = defaultdict(int)
    for a in alerts:
        by_level[a["alert_level"]] += 1

    # Top symbols: count of HIGH+CRITICAL active alerts per symbol
    sym_counts: Dict[str, int] = defaultdict(int)
    for a in alerts:
        if a["status"] == "active" and a["alert_level"] in ("HIGH", "CRITICAL"):
            sym_counts[a["underlying_symbol"]] += 1
    top_symbols = sorted(
        [{"symbol": s, "count": c} for s, c in sym_counts.items()],
        key=lambda x: -x["count"],
    )[:5]

    return {
        "total_alerts": len(alerts),
        "active_alerts": active_hc,
        "alerts_by_level": {
            "CRITICAL": by_level.get("CRITICAL", 0),
            "HIGH": by_level.get("HIGH", 0),
            "MEDIUM": by_level.get("MEDIUM", 0),
            "LOW": by_level.get("LOW", 0),
        },
        "top_symbols": top_symbols,
        "last_run_at": _dt(0.47),  # ~28 minutes ago — recent, still green
    }


# ── In-memory state (rebuilt on startup) ─────────────────────────────────────

_universe: List[dict] = []
_alerts: List[dict] = []
_alert_index: Dict[str, dict] = {}
_events: List[dict] = []


@app.on_event("startup")
async def _startup() -> None:
    global _universe, _alerts, _alert_index, _events
    _universe = _build_universe()
    _alerts = _build_alerts()
    _alert_index = {a["id"]: a for a in _alerts}
    _events = _build_events()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "mode": "demo", "timestamp": _now()}


# ── Universe ──────────────────────────────────────────────────────────────────

@app.get("/api/v1/universe")
async def get_universe():
    return ok(_universe)


@app.post("/api/v1/universe")
async def create_universe_entry(body: dict):
    entry = {
        "id": str(uuid.uuid4()),
        "tenant_id": _TENANT_ID,
        "symbol": body.get("symbol", "").upper(),
        "enabled": body.get("enabled", True),
        "priority": body.get("priority", 5),
        "created_at": _now(),
    }
    _universe.append(entry)
    return ok(entry)


@app.patch("/api/v1/universe/{entry_id}")
async def patch_universe_entry(entry_id: str, body: dict):
    for u in _universe:
        if u["id"] == entry_id:
            u.update({k: v for k, v in body.items() if v is not None})
            return ok(u)
    raise HTTPException(404, "Not found")


@app.delete("/api/v1/universe/{entry_id}", status_code=204)
async def delete_universe_entry(entry_id: str):
    global _universe
    _universe = [u for u in _universe if u["id"] != entry_id]


# ── Alerts ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/alerts")
async def get_alerts(
    symbol: Optional[str] = None,
    alert_level: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    results = list(_alerts)
    if symbol:
        results = [a for a in results if a["underlying_symbol"] == symbol.upper()]
    if alert_level:
        results = [a for a in results if a["alert_level"] == alert_level.upper()]
    if status:
        results = [a for a in results if a["status"] == status.lower()]
    results.sort(key=lambda a: -(a["priority_score"] or 0))
    return ok(results[offset: offset + limit])


@app.get("/api/v1/alerts/{alert_id}")
async def get_alert(alert_id: str):
    a = _alert_index.get(alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    return ok(a)


# ── Metrics ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/metrics/summary")
async def get_metrics():
    return ok(_build_metrics(_alerts))


# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.post("/api/v1/jobs/run-ingestion")
async def run_ingestion():
    return ok({"job_name": "ingestion_job[demo]", "triggered_at": _now(), "status": "triggered"})


@app.post("/api/v1/jobs/run-signal")
async def run_signal():
    return ok({"job_name": "signal_job[demo]", "triggered_at": _now(), "status": "triggered"})


@app.post("/api/v1/jobs/sync-events")
async def sync_events():
    return ok({"providers_run": 1, "results": [{"provider": "demo", "created": 0, "updated": 0, "skipped": 8, "failed": 0, "errors": []}]})


# ── Events ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/events/upcoming")
async def get_upcoming_events():
    return ok(_build_upcoming())


@app.get("/api/v1/events")
async def get_events(
    symbol: Optional[str] = None,
    event_type: Optional[str] = None,
    upcoming_only: bool = False,
    days_ahead: int = 90,
    limit: int = 200,
):
    results = _build_events()
    if symbol:
        results = [e for e in results if e["symbol"] == symbol.upper()]
    if event_type:
        results = [e for e in results if e["event_type"] == event_type]
    if upcoming_only:
        today = date.today().isoformat()
        results = [e for e in results if e["event_date"] >= today]
    return ok(results[:limit])


@app.post("/api/v1/events")
async def create_event(body: dict):
    now = _now()
    event = {
        "id": str(uuid.uuid4()),
        "tenant_id": None,
        "symbol": body.get("symbol", "").upper(),
        "event_type": body.get("event_type", "custom"),
        "title": body.get("title", ""),
        "event_date": body.get("event_date", ""),
        "event_time": body.get("event_time"),
        "source": body.get("source", "manual"),
        "notes": body.get("notes"),
        "created_at": now,
        "updated_at": now,
    }
    _events.append(event)
    return ok(event)


@app.patch("/api/v1/events/{event_id}")
async def patch_event(event_id: str, body: dict):
    for e in _events:
        if e["id"] == event_id:
            e.update({k: v for k, v in body.items() if v is not None})
            e["updated_at"] = _now()
            return ok(e)
    raise HTTPException(404, "Event not found")


@app.delete("/api/v1/events/{event_id}", status_code=204)
async def delete_event(event_id: str):
    global _events
    _events = [e for e in _events if e["id"] != event_id]


@app.post("/api/v1/events/bulk")
async def bulk_create_events(body: list):
    return ok({"created": len(body), "skipped": 0})


# ── Signal Settings ───────────────────────────────────────────────────────────

_SYMBOL_SETTINGS: List[dict] = []


@app.on_event("startup")
async def _startup_settings() -> None:
    global _SYMBOL_SETTINGS
    now = _now()
    _SYMBOL_SETTINGS = [
        {
            "id": "ss-nvda-0000-0000-0000-000000000001",
            "tenant_id": _TENANT_ID, "symbol": "NVDA",
            "min_premium_proxy": None, "max_dte_days": 30,
            "max_moneyness_pct": None, "min_open_interest": None,
            "min_alert_level": None, "enabled": True,
            "priority_weight": 1.5, "watchlist_tier": "core",
            "created_at": now, "updated_at": now,
        },
        {
            "id": "ss-tsla-0000-0000-0000-000000000001",
            "tenant_id": _TENANT_ID, "symbol": "TSLA",
            "min_premium_proxy": None, "max_dte_days": None,
            "max_moneyness_pct": None, "min_open_interest": None,
            "min_alert_level": None, "enabled": True,
            "priority_weight": 1.3, "watchlist_tier": "core",
            "created_at": now, "updated_at": now,
        },
        {
            "id": "ss-aapl-0000-0000-0000-000000000001",
            "tenant_id": _TENANT_ID, "symbol": "AAPL",
            "min_premium_proxy": 5000.0, "max_dte_days": None,
            "max_moneyness_pct": None, "min_open_interest": None,
            "min_alert_level": None, "enabled": True,
            "priority_weight": 1.2, "watchlist_tier": "core",
            "created_at": now, "updated_at": now,
        },
    ]


@app.get("/api/v1/tenants/{tenant_id}/signal-settings")
async def get_tenant_signal_settings(tenant_id: str):
    now = _now()
    return ok({
        "id": "ss000001-0000-0000-0000-000000000001",
        "tenant_id": _TENANT_ID,
        "min_premium_proxy": 2000.0, "max_dte_days": 60,
        "max_moneyness_pct": 0.15, "min_open_interest": 0,
        "min_alert_level": "LOW", "enabled": True,
        "created_at": now, "updated_at": now,
    })


@app.put("/api/v1/tenants/{tenant_id}/signal-settings")
async def put_tenant_signal_settings(tenant_id: str, body: dict):
    now = _now()
    return ok({
        "id": "ss000001-0000-0000-0000-000000000001",
        "tenant_id": _TENANT_ID,
        "created_at": now, "updated_at": now,
        **body,
    })


@app.get("/api/v1/tenants/{tenant_id}/signal-settings/symbols")
async def list_symbol_settings(tenant_id: str):
    return ok(_SYMBOL_SETTINGS)


@app.get("/api/v1/tenants/{tenant_id}/signal-settings/symbols/{symbol}")
async def get_symbol_settings(tenant_id: str, symbol: str):
    for s in _SYMBOL_SETTINGS:
        if s["symbol"] == symbol.upper():
            return ok(s)
    return ok(None)


@app.put("/api/v1/tenants/{tenant_id}/signal-settings/symbols/{symbol}")
async def put_symbol_settings(tenant_id: str, symbol: str, body: dict):
    now = _now()
    new = {
        "id": str(uuid.uuid4()), "tenant_id": _TENANT_ID, "symbol": symbol.upper(),
        "created_at": now, "updated_at": now, **body,
    }
    for i, s in enumerate(_SYMBOL_SETTINGS):
        if s["symbol"] == symbol.upper():
            _SYMBOL_SETTINGS[i] = new
            return ok(new)
    _SYMBOL_SETTINGS.append(new)
    return ok(new)


@app.delete("/api/v1/tenants/{tenant_id}/signal-settings/symbols/{symbol}", status_code=204)
async def delete_symbol_settings(tenant_id: str, symbol: str):
    global _SYMBOL_SETTINGS
    _SYMBOL_SETTINGS = [s for s in _SYMBOL_SETTINGS if s["symbol"] != symbol.upper()]


@app.get("/api/v1/tenants/{tenant_id}/signal-settings/symbols/{symbol}/effective")
async def get_effective_settings(tenant_id: str, symbol: str):
    sym = symbol.upper()
    is_core = sym in ("NVDA", "TSLA", "AAPL")
    weight = {"NVDA": 1.5, "TSLA": 1.3, "AAPL": 1.2}.get(sym, 1.0)
    return ok({
        "min_premium_proxy": 5000.0 if sym == "AAPL" else 2000.0,
        "max_dte_days": 30 if sym == "NVDA" else 60,
        "max_moneyness_pct": 0.15, "min_open_interest": 0,
        "min_alert_level": "LOW", "enabled": True,
        "priority_weight": weight,
        "watchlist_tier": "core" if is_core else "secondary",
        "sources": {
            "min_premium_proxy": "symbol" if sym == "AAPL" else "global",
            "max_dte_days": "symbol" if sym == "NVDA" else "global",
            "max_moneyness_pct": "global", "min_open_interest": "global",
            "min_alert_level": "global", "enabled": "global",
            "priority_weight": "symbol" if weight != 1.0 else "global",
            "watchlist_tier": "symbol" if is_core else "global",
        },
    })


# ── Intelligence ──────────────────────────────────────────────────────────────

@app.get("/api/v1/intelligence/alerts-ranked")
async def get_ranked_alerts(
    symbol: Optional[str] = None,
    alert_level: Optional[str] = None,
    status: Optional[str] = None,
    hours: int = 24,
    limit: int = 20,
):
    results = list(_alerts)
    if symbol:
        results = [a for a in results if a["underlying_symbol"] == symbol.upper()]
    if alert_level:
        results = [a for a in results if a["alert_level"] == alert_level.upper()]
    if status:
        results = [a for a in results if a["status"] == status.lower()]
    results.sort(key=lambda a: -(a["priority_score"] or 0))
    ranked = []
    for a in results[:limit]:
        r = dict(a)
        r["ranked_priority_score"] = a["priority_score"]
        r["contributing_factors"] = a["contributing_factors_json"]
        ranked.append(r)
    return ok(ranked)


@app.get("/api/v1/intelligence/patterns")
async def get_patterns(
    symbol: Optional[str] = None,
    hours: int = 24,
    min_occurrences: int = 2,
):
    patterns = [
        {
            "pattern_type": "repeated_prints",
            "symbol": "NVDA",
            "description": "Unusual call activity at NVDA 820C on 3 consecutive sessions — sustained directional conviction at the same strike.",
            "alert_ids": ["a1000001-0000-0000-0000-000000000001"],
            "strength": 0.94,
            "first_seen_at": _dt(50), "last_seen_at": _dt(1.5),
            "metadata": {"strike": 820.0, "option_type": "C", "sessions": 3},
        },
        {
            "pattern_type": "strike_cluster",
            "symbol": "SPY",
            "description": "Correlated put buying cluster across SPY 560P and QQQ 475P — systematic macro hedge across ETFs ahead of FOMC.",
            "alert_ids": [
                "a1000003-0000-0000-0000-000000000001",
                "a1000007-0000-0000-0000-000000000001",
            ],
            "strength": 0.81,
            "first_seen_at": _dt(3), "last_seen_at": _dt(1.1),
            "metadata": {"macro_event": "FOMC", "days_to_event": 5, "etfs": ["SPY", "QQQ"]},
        },
        {
            "pattern_type": "volume_acceleration",
            "symbol": "SPY",
            "description": "SPY 560P volume accelerating into 3rd consecutive session — programmatic hedge accumulation ahead of FOMC.",
            "alert_ids": ["a1000003-0000-0000-0000-000000000001"],
            "strength": 0.78,
            "first_seen_at": _dt(72), "last_seen_at": _dt(1.0),
            "metadata": {"sessions": 3, "acceleration_factor": 1.4},
        },
        {
            "pattern_type": "expiry_cluster",
            "symbol": "NVDA",
            "description": "Both NVDA call sweep (820C) and protective put (780P) share the same 15-DTE expiry — pre-earnings strangle build-out.",
            "alert_ids": [
                "a1000001-0000-0000-0000-000000000001",
                "a1000009-0000-0000-0000-000000000001",
            ],
            "strength": 0.87,
            "first_seen_at": _dt(2), "last_seen_at": _dt(1.5),
            "metadata": {"expiry_offset": 15, "call_strike": 820.0, "put_strike": 780.0},
        },
    ]
    if symbol:
        patterns = [p for p in patterns if p["symbol"] == symbol.upper()]
    return ok({
        "window_hours": hours,
        "min_occurrences": min_occurrences,
        "alerts_analysed": len(_alerts),
        "patterns_found": len(patterns),
        "patterns": patterns,
        "computed_at": _now(),
    })


@app.get("/api/v1/intelligence/flow-story/{symbol}")
async def get_symbol_flow_story(symbol: str, hours: int = 8):
    sym = symbol.upper()
    sym_alerts = [a for a in _alerts if a["underlying_symbol"] == sym]
    calls = [a for a in sym_alerts if a["option_type"] == "C"]
    puts = [a for a in sym_alerts if a["option_type"] == "P"]
    total = len(sym_alerts)
    call_pct = round(len(calls) / total * 100, 1) if total > 0 else 50.0

    narratives = {
        "NVDA": (
            "NVDA is the standout signal today. Aggressive call sweep at 820C (3rd consecutive session) "
            "combined with protective put buying at 780P ahead of earnings in 6 days — the options market "
            "is pricing in a large move. Priority score 8.9 makes this the highest-conviction alert in the "
            "universe. Worth watching closely into the print."
        ),
        "TSLA": (
            "TSLA showing clean directional conviction via 285C block trade ahead of earnings in 7 days. "
            "Single institutional-size block suggests one large player making a directional bet. "
            "Low-noise signal — no hedging activity visible on the put side."
        ),
        "SPY": (
            "SPY flow is dominated by put buying ahead of FOMC in 5 days. Volume acceleration across "
            "3 sessions with correlated QQQ puts points to systematic macro hedging, not speculation. "
            "The lone 570C represents a small risk-reversal component — net position is defensive."
        ),
        "AAPL": (
            "AAPL showing bifurcated flow: call sweep at 230C (14 days to earnings) alongside "
            "near-term 210P activity. The call side has higher conviction on size and timing. "
            "Worth monitoring the 210P for further accumulation."
        ),
    }
    narrative = narratives.get(sym, f"Flow activity detected in {sym}. Monitoring for follow-through.")

    return ok({
        "symbol": sym,
        "window_hours": hours,
        "session_start": _dt(hours),
        "session_end": _now(),
        "total_alerts": total,
        "alert_distribution": {
            lv: sum(1 for a in sym_alerts if a["alert_level"] == lv)
            for lv in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        },
        "call_put_balance": {"calls": len(calls), "puts": len(puts), "call_pct": call_pct},
        "total_notional": sum(
            (a.get("contributing_factors_json") or {}).get("notional", {}).get("premium_proxy_usd", 0)
            for a in sym_alerts
        ),
        "avg_priority_score": round(
            sum(a["priority_score"] or 0 for a in sym_alerts) / total, 2
        ) if total > 0 else 0.0,
        "dominant_expiries": [],
        "dominant_strikes": [],
        "flow_acceleration": "accelerating" if sym in ("NVDA", "SPY") else "steady",
        "top_alerts": [
            {
                "id": a["id"], "title": a["title"],
                "alert_level": a["alert_level"],
                "anomaly_score": a["anomaly_score"],
                "priority_score": a["priority_score"],
                "created_at": a["created_at"],
            }
            for a in sorted(sym_alerts, key=lambda x: -(x["priority_score"] or 0))[:3]
        ],
        "narrative": narrative,
        "computed_at": _now(),
    })


@app.get("/api/v1/intelligence/flow-story")
async def get_flow_stories(hours: int = 8, top_n: int = 5):
    syms = list({a["underlying_symbol"] for a in _alerts
                 if a["status"] == "active" and a["alert_level"] in ("HIGH", "CRITICAL")})
    syms = sorted(syms, key=lambda s: -(
        max((a["priority_score"] or 0) for a in _alerts if a["underlying_symbol"] == s)
    ))[:top_n]
    stories = []
    for s in syms:
        r = await get_symbol_flow_story(s, hours)
        stories.append(r["data"])
    return ok({
        "window_hours": hours,
        "symbols_requested": top_n,
        "symbols_with_data": len(stories),
        "stories": stories,
        "computed_at": _now(),
    })
