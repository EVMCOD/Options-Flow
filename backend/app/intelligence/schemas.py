"""
Pydantic output schemas for the intelligence API layer.

These types are used by /api/v1/intelligence/* endpoints.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Capacity 1 — Smart Flow Ranking
# ---------------------------------------------------------------------------

class RankedAlertOut(BaseModel):
    """
    Alert enriched with priority_score, ranked_priority_score, and
    structured contributing factors.  Used by GET /intelligence/alerts-ranked.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    underlying_symbol: str
    expiry: date
    strike: Decimal
    option_type: str
    as_of_ts: datetime
    alert_level: str
    anomaly_score: float
    raw_anomaly_score: Optional[float]
    quality_confidence: Optional[float]
    quality_flags: Optional[str]
    dte_at_alert: Optional[int]
    title: str
    explanation: str
    status: str
    created_at: datetime
    # Intelligence fields
    priority_score: Optional[float]              # stored base score (no recency)
    ranked_priority_score: Optional[float]       # priority_score × recency_factor (computed live)
    contributing_factors: Optional[Dict[str, Any]]  # structured factor breakdown


# ---------------------------------------------------------------------------
# Capacity 2 — Pattern Detection
# ---------------------------------------------------------------------------

class PatternMatchOut(BaseModel):
    """
    One detected pattern from GET /intelligence/patterns.
    """
    pattern_type: str    # "repeated_prints" | "strike_cluster" | "expiry_cluster" | "volume_acceleration"
    symbol: str
    description: str
    alert_ids: List[str]
    strength: float      # heuristic 0–1
    first_seen_at: datetime
    last_seen_at: datetime
    metadata: Dict[str, Any]


class PatternDetectionOut(BaseModel):
    """
    Full response from GET /intelligence/patterns.
    """
    window_hours: int
    min_occurrences: int
    alerts_analysed: int
    patterns_found: int
    patterns: List[PatternMatchOut]
    computed_at: datetime


# ---------------------------------------------------------------------------
# Capacity 5 — Intraday Flow Story
# ---------------------------------------------------------------------------

class DominantItemOut(BaseModel):
    label: str
    count: int
    pct: float


class SymbolFlowStoryOut(BaseModel):
    """
    Per-symbol session summary from GET /intelligence/flow-story/{symbol}.
    """
    symbol: str
    window_hours: int
    session_start: Optional[datetime]
    session_end: Optional[datetime]
    total_alerts: int
    alert_distribution: Dict[str, int]
    call_put_balance: Dict[str, Any]
    total_notional: float
    avg_priority_score: float
    dominant_expiries: List[DominantItemOut]
    dominant_strikes: List[DominantItemOut]
    flow_acceleration: str
    top_alerts: List[Dict[str, Any]]
    narrative: str
    computed_at: datetime


class FlowStoryListOut(BaseModel):
    """
    Multi-symbol response from GET /intelligence/flow-story.
    """
    window_hours: int
    symbols_requested: int
    symbols_with_data: int
    stories: List[SymbolFlowStoryOut]
    computed_at: datetime
