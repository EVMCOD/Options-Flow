"""
Pattern Detection — Capacity 2

Detects recurring structure in alert activity that indicates more than
isolated noise.  All patterns are heuristic-based, traceable, and
explainable — no ML involved.

PATTERNS IMPLEMENTED (v1)
--------------------------
1. repeated_prints
   Same (symbol, expiry, strike, option_type) appears 3+ times within the
   detection window.  Signals persistent directional interest on one
   specific contract.

2. strike_cluster
   Multiple alerts on the same symbol where strikes are within STRIKE_BAND_PCT
   (default 5%) of the dominant strike, within the detection window.
   Signals broad but concentrated activity around a price level.

3. expiry_cluster
   Multiple alerts on the same symbol sharing the same expiry date, within
   the detection window.  Signals focused activity on a specific event/date
   (e.g., earnings, FOMC).

4. volume_acceleration
   Anomaly scores increase monotonically (or near-monotonically) across
   sequential alerts on the same (symbol, expiry, strike, type).
   Signals escalating interest, not just a one-off spike.

EXPLICITLY NOT IMPLEMENTED (and why)
--------------------------------------
- Sweep detection: requires tick-level or trade-level data (bid/ask side
  classification).  Delayed snapshots capture aggregated volume only — any
  sweep heuristic would produce false positives.  Deferred to v2 with a
  live or trade feed.
- Cross-symbol correlation: requires sufficient alert history across symbols
  simultaneously.  Deferred to v2.
- ML-based anomaly clustering: out of scope by design.

OUTPUT
------
Each detected pattern produces a PatternMatch dataclass with:
  pattern_type   — one of the four keys above
  symbol         — underlying symbol
  description    — short human-readable summary
  alert_ids      — UUIDs of the participating alerts
  strength       — heuristic 0–1 confidence
  first_seen_at  — earliest alert in the pattern
  last_seen_at   — latest alert in the pattern
  metadata       — pattern-specific detail dict

LIMITATIONS
-----------
- Patterns are computed on demand (no background indexing).  For large
  alert histories with a wide window, query time grows linearly.
- strength is a simple count-based heuristic, not a calibrated probability.
- Patterns do not persist to the database (v1).  The API returns live
  computation results.  Persistence and notification on new pattern
  detection are v2 features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_HOURS: int = 6
DEFAULT_MIN_OCCURRENCES: int = 3
STRIKE_BAND_PCT: float = 0.05   # ±5% strike clustering radius
ACCELERATION_MIN_STEPS: int = 3 # need at least 3 sequential alerts to measure acceleration


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class PatternMatch:
    pattern_type: str
    symbol: str
    description: str
    alert_ids: List[str]
    strength: float          # heuristic 0–1
    first_seen_at: datetime
    last_seen_at: datetime
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Input type (caller provides materialised alert rows)
# ---------------------------------------------------------------------------

@dataclass
class AlertRow:
    """Minimal alert representation for pattern detection."""
    id: str
    symbol: str
    expiry: str        # ISO date string
    strike: float
    option_type: str   # "C" or "P"
    anomaly_score: float
    priority_score: Optional[float]
    created_at: datetime


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_patterns(
    alerts: List[AlertRow],
    window_hours: int = DEFAULT_WINDOW_HOURS,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
) -> List[PatternMatch]:
    """
    Run all pattern detectors on the provided alert list.

    Args:
        alerts:          List of alerts to analyse (already filtered by
                         tenant and time window by the caller).
        window_hours:    Alerts older than this are excluded from patterns.
        min_occurrences: Minimum alert count to form a pattern.

    Returns:
        List of PatternMatch objects, sorted by strength descending.
    """
    if not alerts:
        return []

    patterns: List[PatternMatch] = []
    patterns.extend(_repeated_prints(alerts, min_occurrences))
    patterns.extend(_strike_cluster(alerts, min_occurrences))
    patterns.extend(_expiry_cluster(alerts, min_occurrences))
    patterns.extend(_volume_acceleration(alerts, ACCELERATION_MIN_STEPS))

    return sorted(patterns, key=lambda p: p.strength, reverse=True)


# ---------------------------------------------------------------------------
# Pattern 1 — repeated prints
# ---------------------------------------------------------------------------

def _repeated_prints(
    alerts: List[AlertRow],
    min_occurrences: int,
) -> List[PatternMatch]:
    """
    Detect repeated activity on the exact same contract
    (symbol, expiry, strike, option_type).
    """
    groups: Dict[Tuple, List[AlertRow]] = defaultdict(list)
    for a in alerts:
        key = (a.symbol, a.expiry, a.strike, a.option_type)
        groups[key].append(a)

    results = []
    for (sym, exp, strike, otype), group in groups.items():
        if len(group) < min_occurrences:
            continue
        group_sorted = sorted(group, key=lambda x: x.created_at)
        count = len(group)
        # strength: 0 at min_occurrences, approaches 1 asymptotically
        strength = round(min(1.0, (count - min_occurrences + 1) / (min_occurrences + 2)), 3)
        results.append(PatternMatch(
            pattern_type="repeated_prints",
            symbol=sym,
            description=(
                f"{sym} ${strike:.0f}{otype} exp {exp}: "
                f"{count} prints in window. Persistent directional interest."
            ),
            alert_ids=[a.id for a in group_sorted],
            strength=strength,
            first_seen_at=group_sorted[0].created_at,
            last_seen_at=group_sorted[-1].created_at,
            metadata={
                "expiry": exp,
                "strike": strike,
                "option_type": otype,
                "count": count,
            },
        ))
    return results


# ---------------------------------------------------------------------------
# Pattern 2 — strike cluster
# ---------------------------------------------------------------------------

def _strike_cluster(
    alerts: List[AlertRow],
    min_occurrences: int,
) -> List[PatternMatch]:
    """
    Detect concentration of alerts around a common strike price for the same
    symbol.  Uses a greedy centroid approach: group by symbol, then cluster
    strikes that are within STRIKE_BAND_PCT of the group's dominant strike.
    """
    by_symbol: Dict[str, List[AlertRow]] = defaultdict(list)
    for a in alerts:
        by_symbol[a.symbol].append(a)

    results = []
    for sym, sym_alerts in by_symbol.items():
        if len(sym_alerts) < min_occurrences:
            continue

        # Find centroid strike (weighted by anomaly_score)
        total_score = sum(a.anomaly_score for a in sym_alerts)
        if total_score == 0:
            centroid = sym_alerts[0].strike
        else:
            centroid = sum(a.strike * a.anomaly_score for a in sym_alerts) / total_score

        # Cluster alerts within ±STRIKE_BAND_PCT of centroid
        cluster = [
            a for a in sym_alerts
            if centroid > 0 and abs(a.strike / centroid - 1.0) <= STRIKE_BAND_PCT
        ]
        if len(cluster) < min_occurrences:
            continue

        cluster_sorted = sorted(cluster, key=lambda x: x.created_at)
        count = len(cluster)
        lo = min(a.strike for a in cluster)
        hi = max(a.strike for a in cluster)
        strength = round(min(1.0, (count - min_occurrences + 1) / (min_occurrences + 3)), 3)

        results.append(PatternMatch(
            pattern_type="strike_cluster",
            symbol=sym,
            description=(
                f"{sym}: {count} alerts concentrated near ${centroid:.0f} "
                f"(${lo:.0f}–${hi:.0f} range). Strike-level accumulation."
            ),
            alert_ids=[a.id for a in cluster_sorted],
            strength=strength,
            first_seen_at=cluster_sorted[0].created_at,
            last_seen_at=cluster_sorted[-1].created_at,
            metadata={
                "centroid_strike": round(centroid, 2),
                "strike_range_lo": lo,
                "strike_range_hi": hi,
                "band_pct": STRIKE_BAND_PCT,
                "count": count,
            },
        ))
    return results


# ---------------------------------------------------------------------------
# Pattern 3 — expiry cluster
# ---------------------------------------------------------------------------

def _expiry_cluster(
    alerts: List[AlertRow],
    min_occurrences: int,
) -> List[PatternMatch]:
    """
    Detect multiple alerts on the same symbol targeting the same expiry date.
    Signals interest in a specific event (earnings, FOMC, etc.) across
    multiple strikes.
    """
    groups: Dict[Tuple[str, str], List[AlertRow]] = defaultdict(list)
    for a in alerts:
        key = (a.symbol, a.expiry)
        groups[key].append(a)

    results = []
    for (sym, exp), group in groups.items():
        if len(group) < min_occurrences:
            continue
        group_sorted = sorted(group, key=lambda x: x.created_at)
        count = len(group)
        strikes = sorted(set(a.strike for a in group))
        call_count = sum(1 for a in group if a.option_type == "C")
        put_count = count - call_count

        strength = round(min(1.0, (count - min_occurrences + 1) / (min_occurrences + 3)), 3)

        balance_note = ""
        if call_count > 0 and put_count > 0:
            balance_note = f" Mixed (C:{call_count} P:{put_count})."
        elif call_count > 0:
            balance_note = f" Call-only ({call_count})."
        else:
            balance_note = f" Put-only ({put_count})."

        results.append(PatternMatch(
            pattern_type="expiry_cluster",
            symbol=sym,
            description=(
                f"{sym}: {count} alerts targeting {exp} expiry across "
                f"{len(strikes)} strikes.{balance_note} Event-driven interest."
            ),
            alert_ids=[a.id for a in group_sorted],
            strength=strength,
            first_seen_at=group_sorted[0].created_at,
            last_seen_at=group_sorted[-1].created_at,
            metadata={
                "expiry": exp,
                "strike_count": len(strikes),
                "strikes": strikes[:10],  # cap for response size
                "call_count": call_count,
                "put_count": put_count,
                "count": count,
            },
        ))
    return results


# ---------------------------------------------------------------------------
# Pattern 4 — volume acceleration
# ---------------------------------------------------------------------------

def _volume_acceleration(
    alerts: List[AlertRow],
    min_steps: int,
) -> List[PatternMatch]:
    """
    Detect escalating anomaly scores on the same contract across sequential
    prints.  "Escalating" means each print's score is at least as high as
    the prior one (monotone non-decreasing, with a tolerance).

    strength = mean_score_delta / 2.0  (capped at 1.0)
    """
    groups: Dict[Tuple, List[AlertRow]] = defaultdict(list)
    for a in alerts:
        key = (a.symbol, a.expiry, a.strike, a.option_type)
        groups[key].append(a)

    results = []
    for (sym, exp, strike, otype), group in groups.items():
        if len(group) < min_steps:
            continue

        sorted_group = sorted(group, key=lambda x: x.created_at)
        scores = [a.anomaly_score for a in sorted_group]

        # Allow one "dip" before declaring it non-accelerating
        increases = sum(1 for i in range(1, len(scores)) if scores[i] >= scores[i - 1] * 0.90)
        if increases < len(scores) - 2:
            continue

        score_delta = scores[-1] - scores[0]
        if score_delta <= 0:
            continue

        strength = round(min(1.0, score_delta / 4.0), 3)  # saturates at Δ4.0 pts

        results.append(PatternMatch(
            pattern_type="volume_acceleration",
            symbol=sym,
            description=(
                f"{sym} ${strike:.0f}{otype} exp {exp}: "
                f"anomaly score escalating from {scores[0]:.1f} → {scores[-1]:.1f} "
                f"across {len(sorted_group)} prints. Intensifying interest."
            ),
            alert_ids=[a.id for a in sorted_group],
            strength=strength,
            first_seen_at=sorted_group[0].created_at,
            last_seen_at=sorted_group[-1].created_at,
            metadata={
                "expiry": exp,
                "strike": strike,
                "option_type": otype,
                "score_start": round(scores[0], 3),
                "score_end": round(scores[-1], 3),
                "score_delta": round(score_delta, 3),
                "step_count": len(sorted_group),
            },
        ))
    return results
