"""
Smart Flow Ranking — Capacity 1

Computes priority_score for alerts: a composite 0–10 metric that combines
statistical signal strength, economic relevance, data quality, and
per-client symbol personalization.

FORMULA
-------
Base score (stored on alert at creation time — recency-independent):

  base = (
      0.45 × norm_anomaly       # statistical signal strength
    + 0.30 × norm_premium       # economic / notional relevance
    + 0.25 × quality_confidence # data quality
  ) × priority_weight × 10

  norm_anomaly   = anomaly_score / 10          (anomaly_score already 0–10)
  norm_premium   = clamp(premium_proxy / 50_000, 0, 1)  saturates at $50k
  quality_confidence already in [0.5, 1.0]

  priority_weight (default 1.0) is the per-client symbol multiplier from
  TenantSymbolSettings.  Range 0.0–3.0.

Ranked score (computed at query time — applies recency decay):

  ranked = base × recency_factor
  recency_factor = exp(-RECENCY_DECAY × hours_since_creation)
  RECENCY_DECAY = 0.05  →  half-life ≈ 14 hours

Design decisions:
  - base_score is stable and meaningful for historical comparisons.
  - recency is applied only in the ranking endpoint so queries at different
    times give consistent relative ordering of old vs new alerts.
  - quality_confidence is already applied to anomaly_score; including it
    again as an additive term means quality also boosts the ranking directly.
  - priority_weight > 1.0 can push a symbol's alerts above their raw score.
    Intentional: clients can flag symbols they watch closely.
  - priority_weight = 0 suppresses an alert from ranked results entirely
    (score → 0) without deleting it from the database.

CONTRIBUTING FACTORS
--------------------
Structured JSON stored on each alert for the Actionable Explanations feature.
Schema defined below in _contributing_factors_schema.  Key:
  volume_spike  — statistical anomaly detail + human label
  notional      — USD premium proxy + size category
  timing        — DTE + urgency label
  quality       — data flags + confidence + feed type
  moneyness     — distance from spot + label (ITM/ATM/OTM)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECENCY_DECAY: float = 0.05          # per-hour decay; half-life ≈ 14h
NOTIONAL_SATURATION: float = 50_000  # $50k premium proxy → norm = 1.0
WEIGHTS = {"anomaly": 0.45, "premium": 0.30, "quality": 0.25}


# ---------------------------------------------------------------------------
# Base priority score (stored at alert creation)
# ---------------------------------------------------------------------------

def compute_priority_score(
    anomaly_score: float,
    premium_proxy: Optional[float],
    quality_confidence: float,
    priority_weight: float = 1.0,
) -> float:
    """
    Compute the intrinsic priority score (0–10) for an alert.

    Does NOT include recency — call ranked_priority_score() to apply
    recency decay at query time.

    Args:
        anomaly_score:      Quality-adjusted anomaly score (0–10).
        premium_proxy:      Estimated notional in USD (volume × mid × 100).
                            None treated as 0.
        quality_confidence: Data quality multiplier (0.5–1.0).
        priority_weight:    Per-symbol client multiplier (default 1.0).
                            Comes from TenantSymbolSettings.priority_weight.
    Returns:
        Float 0–10 (clamped).  Returns 0 if priority_weight == 0.
    """
    if priority_weight <= 0.0:
        return 0.0

    norm_anomaly = _clamp(anomaly_score / 10.0, 0.0, 1.0)
    norm_premium = _clamp((premium_proxy or 0.0) / NOTIONAL_SATURATION, 0.0, 1.0)
    norm_quality = _clamp(quality_confidence, 0.5, 1.0)  # already in range

    raw = (
        WEIGHTS["anomaly"] * norm_anomaly
        + WEIGHTS["premium"] * norm_premium
        + WEIGHTS["quality"] * norm_quality
    ) * priority_weight * 10.0

    return round(_clamp(raw, 0.0, 10.0), 3)


def ranked_priority_score(
    base_priority_score: float,
    created_at: datetime,
    now: Optional[datetime] = None,
) -> float:
    """
    Apply recency decay to a stored base_priority_score.

    Use this in the ranking endpoint — never store the result.

    Args:
        base_priority_score: Value from alert.priority_score.
        created_at:          When the alert was created.
        now:                 Reference time (defaults to UTC now).
    Returns:
        Decayed score, rounded to 3 decimal places.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Normalise timezone awareness before subtraction
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    hours_old = max(0.0, (now - created_at).total_seconds() / 3600.0)
    recency = math.exp(-RECENCY_DECAY * hours_old)
    return round(base_priority_score * recency, 3)


# ---------------------------------------------------------------------------
# Contributing factors (Capacity 4 — Actionable Alert Explanations)
# ---------------------------------------------------------------------------

def build_contributing_factors(
    volume_ratio: float,
    volume_zscore: float,
    baseline_volume: float,
    current_volume: int,
    premium_proxy: Optional[float],
    dte: int,
    quality_confidence: float,
    quality_flags: List[str],
    spot: float,
    strike: float,
    option_type: str,        # "C" or "P"
    iv: Optional[float],
    data_source: str = "ibkr_delayed",
) -> dict:
    """
    Build a machine-readable factor breakdown stored on each alert.

    Schema:
      volume_spike: { ratio, baseline_avg, current, zscore, assessment }
      notional:     { premium_proxy_usd, assessment }
      timing:       { dte, assessment }
      quality:      { confidence, flags, data_source, assessment }
      moneyness:    { spot, strike, distance_pct, label }
      iv:           { value } | null
    """
    moneyness_ratio = spot / strike if strike > 0 else 1.0
    distance_pct = round(abs(moneyness_ratio - 1.0), 4)

    if moneyness_ratio > 1.05:
        moneyness_label = "ITM" if option_type == "C" else "OTM"
    elif moneyness_ratio < 0.95:
        moneyness_label = "OTM" if option_type == "C" else "ITM"
    else:
        moneyness_label = "ATM"

    return {
        "volume_spike": {
            "ratio": round(volume_ratio, 2),
            "baseline_avg": round(baseline_volume, 0),
            "current": current_volume,
            "zscore": round(volume_zscore, 2),
            "assessment": _spike_assessment(volume_ratio),
        },
        "notional": {
            "premium_proxy_usd": round(premium_proxy or 0.0, 0),
            "assessment": _notional_assessment(premium_proxy or 0.0),
        },
        "timing": {
            "dte": dte,
            "assessment": _dte_assessment(dte),
        },
        "quality": {
            "confidence": round(quality_confidence, 3),
            "flags": quality_flags,
            "data_source": data_source,
            "assessment": _quality_assessment(quality_confidence),
        },
        "moneyness": {
            "spot": round(spot, 2),
            "strike": round(strike, 2),
            "distance_pct": distance_pct,
            "label": moneyness_label,
        },
        **({"iv": {"value": round(iv, 4)}} if iv is not None else {"iv": None}),
    }


# ---------------------------------------------------------------------------
# Enhanced explanation text (Capacity 4)
# ---------------------------------------------------------------------------

def build_enhanced_explanation(
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
    factors: dict,
    alert_level: str,
    anomaly_score: float,
    raw_score: float,
    quality_confidence: float,
) -> str:
    """
    Build a concise, factual alert explanation using the structured factors.

    Format:
      [LEVEL] SYMBOL STRIKE(C|P) · expEXPIRY (NdDTE) · MONEYNESS_LABEL
      Vol spike: CURRENT vs baseline BASELINE — RATIO× (z ZSCORE). [SPIKE_LABEL]
      Premium proxy: ~$NOTIONAL. [NOTIONAL_LABEL].
      [IV line if available.]
      Score: SCORE/10 [raw RAW, −X% quality]. Data: SOURCE · [flags].
    """
    otype = "C" if option_type == "C" else "P"
    dte = factors["timing"]["dte"]
    dte_str = f" ({dte}DTE)" if 0 <= dte <= 9998 else ""
    money = factors["moneyness"]["label"]

    spike = factors["volume_spike"]
    notional = factors["notional"]
    qual = factors["quality"]

    lines: List[str] = []

    # Header
    lines.append(
        f"[{alert_level}] {symbol} ${strike:.0f}{otype} · exp {expiry}{dte_str} · {money}"
    )

    # Volume spike
    spike_detail = (
        f"Vol spike: {spike['current']:,} vs baseline {spike['baseline_avg']:.0f} — "
        f"{spike['ratio']:.1f}× (z {spike['zscore']:+.1f}). {_label(spike['assessment'])}."
    )
    lines.append(spike_detail)

    # Notional
    if notional["premium_proxy_usd"] > 0:
        lines.append(
            f"Premium proxy: ~${notional['premium_proxy_usd']:,.0f}. {_label(notional['assessment'])}."
        )

    # IV
    iv_data = factors.get("iv")
    if iv_data and iv_data.get("value") is not None:
        lines.append(f"IV: {iv_data['value']:.1%}.")

    # Score + quality
    if quality_confidence < 1.0:
        penalty_pct = round((1.0 - quality_confidence) * 100)
        score_line = f"Score: {anomaly_score:.2f}/10 [raw {raw_score:.2f}, −{penalty_pct}% quality]."
    else:
        score_line = f"Score: {anomaly_score:.2f}/10."

    flags_str = " · ".join(qual["flags"]) if qual["flags"] else "clean"
    lines.append(f"{score_line} Data: {qual['data_source']} · {flags_str}.")

    return " ".join(lines)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _spike_assessment(ratio: float) -> str:
    if ratio >= 10.0:
        return "extreme"
    if ratio >= 5.0:
        return "very_high"
    if ratio >= 3.0:
        return "high"
    return "elevated"


def _notional_assessment(usd: float) -> str:
    if usd >= 500_000:
        return "institutional"
    if usd >= 100_000:
        return "large"
    if usd >= 20_000:
        return "moderate"
    return "small"


def _dte_assessment(dte: int) -> str:
    if dte <= 5:
        return "near_term"
    if dte <= 14:
        return "short_term"
    if dte <= 30:
        return "medium_term"
    return "long_term"


def _quality_assessment(confidence: float) -> str:
    if confidence >= 0.95:
        return "clean"
    if confidence >= 0.80:
        return "minor_flags"
    return "reduced"


def _label(assessment: str) -> str:
    """Convert snake_case assessment to title-cased human label."""
    return assessment.replace("_", " ").title()
