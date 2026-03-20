"""
Intraday Flow Story — Capacity 5

Generates a per-symbol session summary from recent alert activity.
Computed on demand (no persistence in v1) — each API call queries
the last N hours of alerts for the requested symbol(s).

OUTPUT — SymbolFlowStory
  symbol              — underlying symbol
  window_hours        — lookback window used for this computation
  session_start       — earliest alert in window
  session_end         — latest alert in window (or now if no alerts)
  total_alerts        — count in window
  alert_distribution  — breakdown by level (LOW/MEDIUM/HIGH/CRITICAL)
  call_put_balance    — calls vs puts count + call fraction
  total_notional      — sum of premium_proxy across alerts in window
  avg_priority_score  — mean priority_score of alerts in window
  dominant_expiries   — top 3 expiries by alert count
  dominant_strikes    — top 3 strikes by alert count
  flow_acceleration   — "accelerating" | "steady" | "decelerating" | "insufficient_data"
  top_alerts          — top 3 alerts by priority_score (for quick inspection)
  narrative           — 2–4 sentence plain-language summary
  computed_at         — UTC timestamp when this story was computed

FLOW ACCELERATION HEURISTIC
  Need at least 6 alerts to compute.
  Divide window into thirds (early / mid / late) by time.
  - late/early ratio ≥ 1.5  → "accelerating"
  - late/early ratio ≤ 0.67 → "decelerating"
  - otherwise               → "steady"

NARRATIVE GENERATION
  Deterministic string construction — no LLM or ML.
  Structure:
    1. Volume summary (N alerts, $X notional, window).
    2. Directional balance (call-heavy / put-heavy / mixed).
    3. Concentration note (dominant expiry/strike if clear).
    4. Acceleration note (if determinable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import Counter


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class DominantItem:
    label: str       # expiry date or strike price as string
    count: int
    pct: float       # fraction of total alerts


@dataclass
class SymbolFlowStory:
    symbol: str
    window_hours: int
    session_start: Optional[datetime]    # None when no alerts in window
    session_end: Optional[datetime]
    total_alerts: int
    alert_distribution: Dict[str, int]  # {"LOW": N, "MEDIUM": N, ...}
    call_put_balance: Dict[str, object] # {"calls": N, "puts": N, "call_pct": float}
    total_notional: float
    avg_priority_score: float
    dominant_expiries: List[DominantItem]
    dominant_strikes: List[DominantItem]
    flow_acceleration: str              # "accelerating" | "steady" | "decelerating" | "insufficient_data"
    top_alerts: List[dict]              # top 3 by priority_score
    narrative: str
    computed_at: datetime


# ---------------------------------------------------------------------------
# Input type
# ---------------------------------------------------------------------------

@dataclass
class AlertStoryRow:
    """Minimal alert view needed for flow story computation."""
    id: str
    symbol: str
    expiry: str          # ISO date string
    strike: float
    option_type: str     # "C" or "P"
    alert_level: str
    anomaly_score: float
    priority_score: Optional[float]
    premium_proxy: Optional[float]
    created_at: datetime
    title: str


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_flow_story(
    symbol: str,
    alerts: List[AlertStoryRow],
    window_hours: int = 8,
    now: Optional[datetime] = None,
) -> SymbolFlowStory:
    """
    Compute the flow story for one symbol from its recent alerts.

    Args:
        symbol:       The underlying symbol.
        alerts:       Alert rows for this symbol within the window
                      (filtered/ordered by the caller).
        window_hours: Lookback window in hours (for narrative).
        now:          Reference time (defaults to UTC now).
    Returns:
        SymbolFlowStory
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if not alerts:
        return _empty_story(symbol, window_hours, now)

    sorted_alerts = sorted(alerts, key=lambda a: a.created_at)

    session_start = sorted_alerts[0].created_at
    session_end = sorted_alerts[-1].created_at
    total = len(sorted_alerts)

    # Alert distribution
    dist: Dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for a in sorted_alerts:
        level = a.alert_level.upper()
        if level in dist:
            dist[level] += 1

    # Call / put balance
    calls = sum(1 for a in sorted_alerts if a.option_type == "C")
    puts = total - calls
    call_pct = round(calls / total, 3) if total > 0 else 0.5
    balance = {"calls": calls, "puts": puts, "call_pct": call_pct}

    # Total notional & avg priority
    total_notional = sum(a.premium_proxy or 0.0 for a in sorted_alerts)
    scores = [a.priority_score for a in sorted_alerts if a.priority_score is not None]
    avg_priority = round(sum(scores) / len(scores), 3) if scores else 0.0

    # Dominant expiries
    expiry_counter = Counter(a.expiry for a in sorted_alerts)
    dominant_expiries = [
        DominantItem(label=exp, count=cnt, pct=round(cnt / total, 3))
        for exp, cnt in expiry_counter.most_common(3)
    ]

    # Dominant strikes
    strike_counter = Counter(a.strike for a in sorted_alerts)
    dominant_strikes = [
        DominantItem(label=f"${strike:.0f}", count=cnt, pct=round(cnt / total, 3))
        for strike, cnt in strike_counter.most_common(3)
    ]

    # Flow acceleration
    acceleration = _compute_acceleration(sorted_alerts)

    # Top 3 by priority_score
    top_alerts = sorted(
        sorted_alerts,
        key=lambda a: a.priority_score or 0.0,
        reverse=True,
    )[:3]
    top_alerts_out = [
        {
            "id": a.id,
            "title": a.title,
            "alert_level": a.alert_level,
            "anomaly_score": a.anomaly_score,
            "priority_score": a.priority_score,
            "created_at": a.created_at.isoformat(),
        }
        for a in top_alerts
    ]

    # Narrative
    narrative = _build_narrative(
        symbol=symbol,
        total=total,
        window_hours=window_hours,
        total_notional=total_notional,
        balance=balance,
        dominant_expiries=dominant_expiries,
        dominant_strikes=dominant_strikes,
        acceleration=acceleration,
        dist=dist,
    )

    return SymbolFlowStory(
        symbol=symbol,
        window_hours=window_hours,
        session_start=session_start,
        session_end=session_end,
        total_alerts=total,
        alert_distribution=dist,
        call_put_balance=balance,
        total_notional=round(total_notional, 0),
        avg_priority_score=avg_priority,
        dominant_expiries=dominant_expiries,
        dominant_strikes=dominant_strikes,
        flow_acceleration=acceleration,
        top_alerts=top_alerts_out,
        narrative=narrative,
        computed_at=now,
    )


# ---------------------------------------------------------------------------
# Flow acceleration heuristic
# ---------------------------------------------------------------------------

def _compute_acceleration(alerts: List[AlertStoryRow]) -> str:
    if len(alerts) < 6:
        return "insufficient_data"

    start = alerts[0].created_at
    end = alerts[-1].created_at
    total_span = (end - start).total_seconds()

    if total_span < 1:
        return "insufficient_data"

    third = total_span / 3.0
    early_cutoff = start.timestamp() + third
    late_cutoff = start.timestamp() + 2 * third

    early = sum(1 for a in alerts if a.created_at.timestamp() <= early_cutoff)
    late = sum(1 for a in alerts if a.created_at.timestamp() >= late_cutoff)

    if early == 0:
        return "accelerating"
    ratio = late / early

    if ratio >= 1.5:
        return "accelerating"
    if ratio <= 0.67:
        return "decelerating"
    return "steady"


# ---------------------------------------------------------------------------
# Narrative builder
# ---------------------------------------------------------------------------

def _build_narrative(
    symbol: str,
    total: int,
    window_hours: int,
    total_notional: float,
    balance: dict,
    dominant_expiries: List[DominantItem],
    dominant_strikes: List[DominantItem],
    acceleration: str,
    dist: dict,
) -> str:
    parts: List[str] = []

    # 1. Volume + notional summary
    notional_str = f" (~${total_notional / 1_000:.0f}k notional)" if total_notional >= 1_000 else ""
    parts.append(
        f"{symbol} generated {total} alert{'s' if total != 1 else ''} "
        f"in the last {window_hours}h{notional_str}."
    )

    # 2. Directional balance
    calls = balance["calls"]
    puts = balance["puts"]
    call_pct = balance["call_pct"]
    if calls == 0 and puts == 0:
        pass
    elif call_pct >= 0.75:
        parts.append(f"Strongly call-sided ({calls}C vs {puts}P).")
    elif call_pct <= 0.25:
        parts.append(f"Strongly put-sided ({puts}P vs {calls}C).")
    elif call_pct >= 0.6:
        parts.append(f"Mildly call-biased ({calls}C vs {puts}P).")
    elif call_pct <= 0.4:
        parts.append(f"Mildly put-biased ({puts}P vs {calls}C).")
    else:
        parts.append(f"Balanced flow ({calls}C / {puts}P).")

    # 3. Concentration note
    if dominant_expiries and dominant_expiries[0].pct >= 0.60 and len(dominant_expiries) >= 1:
        top_exp = dominant_expiries[0]
        parts.append(
            f"Activity concentrated on {top_exp.label} expiry "
            f"({top_exp.pct:.0%} of alerts)."
        )
    if dominant_strikes and dominant_strikes[0].pct >= 0.50 and len(dominant_strikes) >= 1:
        top_s = dominant_strikes[0]
        parts.append(f"Dominant strike: {top_s.label} ({top_s.count} alerts).")

    # 4. Acceleration
    accel_phrases = {
        "accelerating": "Flow is accelerating — activity picking up in the recent window.",
        "decelerating": "Flow is decelerating — activity was heavier earlier in the window.",
        "steady": "Flow is steady — consistent activity throughout the window.",
    }
    if acceleration in accel_phrases:
        parts.append(accel_phrases[acceleration])

    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Empty story helper
# ---------------------------------------------------------------------------

def _empty_story(symbol: str, window_hours: int, now: datetime) -> SymbolFlowStory:
    return SymbolFlowStory(
        symbol=symbol,
        window_hours=window_hours,
        session_start=None,
        session_end=None,
        total_alerts=0,
        alert_distribution={"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0},
        call_put_balance={"calls": 0, "puts": 0, "call_pct": 0.5},
        total_notional=0.0,
        avg_priority_score=0.0,
        dominant_expiries=[],
        dominant_strikes=[],
        flow_acceleration="insufficient_data",
        top_alerts=[],
        narrative=f"No alerts for {symbol} in the last {window_hours}h.",
        computed_at=now,
    )
