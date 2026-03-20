"""
Intelligence API — Capacities 1, 2, 5

Endpoints:
  GET /api/v1/intelligence/alerts-ranked
      Smart Flow Ranking: alerts sorted by ranked_priority_score.
      Combines anomaly strength, notional size, quality, freshness, and
      per-client symbol weight.

  GET /api/v1/intelligence/patterns
      Pattern Detection: detect repeated prints, strike/expiry clusters,
      and volume acceleration within a configurable time window.

  GET /api/v1/intelligence/flow-story/{symbol}
      Intraday Flow Story: per-symbol session summary with acceleration,
      directional balance, dominant expiries/strikes, and narrative.

  GET /api/v1/intelligence/flow-story
      Multi-symbol flow stories for the top N most active symbols.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging_setup import get_logger
from app.models.models import Alert
from app.schemas.schemas import ApiResponse
from app.intelligence.ranking import ranked_priority_score
from app.intelligence.patterns import AlertRow, PatternMatch, detect_patterns
from app.intelligence.flow_story import AlertStoryRow, compute_flow_story
from app.intelligence.schemas import (
    FlowStoryListOut,
    PatternDetectionOut,
    PatternMatchOut,
    RankedAlertOut,
    SymbolFlowStoryOut,
    DominantItemOut,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])
log = get_logger(__name__)

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_contributing_factors(alert: Alert) -> Optional[dict]:
    """Return contributing_factors_json or None."""
    cf = getattr(alert, "contributing_factors_json", None)
    if cf is None:
        return None
    if isinstance(cf, dict):
        return cf
    try:
        return json.loads(cf)
    except Exception:
        return None


def _story_to_out(story) -> SymbolFlowStoryOut:
    return SymbolFlowStoryOut(
        symbol=story.symbol,
        window_hours=story.window_hours,
        session_start=story.session_start,
        session_end=story.session_end,
        total_alerts=story.total_alerts,
        alert_distribution=story.alert_distribution,
        call_put_balance=story.call_put_balance,
        total_notional=story.total_notional,
        avg_priority_score=story.avg_priority_score,
        dominant_expiries=[
            DominantItemOut(label=d.label, count=d.count, pct=d.pct)
            for d in story.dominant_expiries
        ],
        dominant_strikes=[
            DominantItemOut(label=d.label, count=d.count, pct=d.pct)
            for d in story.dominant_strikes
        ],
        flow_acceleration=story.flow_acceleration,
        top_alerts=story.top_alerts,
        narrative=story.narrative,
        computed_at=story.computed_at,
    )


# ---------------------------------------------------------------------------
# GET /intelligence/alerts-ranked — Capacity 1
# ---------------------------------------------------------------------------

@router.get("/alerts-ranked", response_model=ApiResponse[List[RankedAlertOut]])
async def list_alerts_ranked(
    tenant_id: Optional[uuid.UUID] = Query(None),
    symbol: Optional[str] = Query(None),
    alert_level: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168, description="Only consider alerts from the last N hours"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Return alerts sorted by ranked_priority_score (high → low).

    ranked_priority_score = priority_score × recency_factor
    recency_factor = exp(-0.05 × hours_since_creation)
    half-life ≈ 14 hours.

    Alerts without a stored priority_score fall back to anomaly_score/10.
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    q = (
        select(Alert)
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.created_at >= cutoff)
    )
    if symbol:
        q = q.where(Alert.underlying_symbol == symbol.upper())
    if alert_level:
        q = q.where(Alert.alert_level == alert_level.upper())
    if status:
        q = q.where(Alert.status == status.lower())

    # Fetch up to limit*3 rows then re-sort in Python (ranking changes with recency)
    q = q.limit(min(limit * 3, 600))
    result = await db.execute(q)
    alerts: List[Alert] = list(result.scalars().all())

    now = datetime.now(timezone.utc)

    def _rank(a: Alert) -> float:
        base = getattr(a, "priority_score", None) or (a.anomaly_score / 10.0)
        return ranked_priority_score(base, a.created_at, now)

    ranked = sorted(alerts, key=_rank, reverse=True)[:limit]

    out = []
    for a in ranked:
        base = getattr(a, "priority_score", None) or (a.anomaly_score / 10.0)
        ranked_score = ranked_priority_score(base, a.created_at, now)
        out.append(
            RankedAlertOut(
                id=a.id,
                underlying_symbol=a.underlying_symbol,
                expiry=a.expiry,
                strike=a.strike,
                option_type=a.option_type,
                as_of_ts=a.as_of_ts,
                alert_level=a.alert_level,
                anomaly_score=a.anomaly_score,
                raw_anomaly_score=getattr(a, "raw_anomaly_score", None),
                quality_confidence=getattr(a, "quality_confidence", None),
                quality_flags=getattr(a, "quality_flags", None),
                dte_at_alert=getattr(a, "dte_at_alert", None),
                title=a.title,
                explanation=a.explanation,
                status=a.status,
                created_at=a.created_at,
                priority_score=getattr(a, "priority_score", None),
                ranked_priority_score=ranked_score,
                contributing_factors=_parse_contributing_factors(a),
            )
        )

    return ApiResponse.ok(out)


# ---------------------------------------------------------------------------
# GET /intelligence/patterns — Capacity 2
# ---------------------------------------------------------------------------

@router.get("/patterns", response_model=ApiResponse[PatternDetectionOut])
async def detect_flow_patterns(
    tenant_id: Optional[uuid.UUID] = Query(None),
    symbol: Optional[str] = Query(None, description="Filter to one symbol"),
    hours: int = Query(6, ge=1, le=48, description="Detection window in hours"),
    min_occurrences: int = Query(3, ge=2, le=20, description="Minimum alerts to form a pattern"),
    db: AsyncSession = Depends(get_db),
):
    """
    Detect recurring patterns in recent alert activity.

    Patterns detected:
    - repeated_prints: Same contract (symbol/expiry/strike/type) ≥ N times.
    - strike_cluster: Multiple alerts near the same strike for one symbol.
    - expiry_cluster: Multiple alerts targeting the same expiry for one symbol.
    - volume_acceleration: Escalating anomaly scores on the same contract.
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    q = (
        select(Alert)
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.created_at >= cutoff)
        .order_by(Alert.created_at.asc())
        .limit(1000)  # safety cap; patterns need only recent data
    )
    if symbol:
        q = q.where(Alert.underlying_symbol == symbol.upper())

    result = await db.execute(q)
    raw_alerts: List[Alert] = list(result.scalars().all())

    alert_rows = [
        AlertRow(
            id=str(a.id),
            symbol=a.underlying_symbol,
            expiry=str(a.expiry),
            strike=float(a.strike),
            option_type=a.option_type,
            anomaly_score=a.anomaly_score,
            priority_score=getattr(a, "priority_score", None),
            created_at=a.created_at,
        )
        for a in raw_alerts
    ]

    patterns: List[PatternMatch] = detect_patterns(
        alert_rows, window_hours=hours, min_occurrences=min_occurrences
    )

    now = datetime.now(timezone.utc)

    return ApiResponse.ok(
        PatternDetectionOut(
            window_hours=hours,
            min_occurrences=min_occurrences,
            alerts_analysed=len(alert_rows),
            patterns_found=len(patterns),
            patterns=[
                PatternMatchOut(
                    pattern_type=p.pattern_type,
                    symbol=p.symbol,
                    description=p.description,
                    alert_ids=p.alert_ids,
                    strength=p.strength,
                    first_seen_at=p.first_seen_at,
                    last_seen_at=p.last_seen_at,
                    metadata=p.metadata,
                )
                for p in patterns
            ],
            computed_at=now,
        )
    )


# ---------------------------------------------------------------------------
# GET /intelligence/flow-story/{symbol} — Capacity 5
# ---------------------------------------------------------------------------

@router.get("/flow-story/{symbol}", response_model=ApiResponse[SymbolFlowStoryOut])
async def get_flow_story(
    symbol: str,
    tenant_id: Optional[uuid.UUID] = Query(None),
    hours: int = Query(8, ge=1, le=72, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate the intraday flow story for one symbol.

    Returns a structured summary including:
    - Alert volume and level distribution
    - Call/put directional balance
    - Dominant expiries and strikes
    - Flow acceleration (accelerating / steady / decelerating)
    - Total estimated notional
    - Top 3 alerts by priority
    - Plain-language narrative
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sym_upper = symbol.upper()

    q = (
        select(Alert)
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.underlying_symbol == sym_upper)
        .where(Alert.created_at >= cutoff)
        .order_by(Alert.created_at.asc())
        .limit(500)
    )
    result = await db.execute(q)
    raw_alerts: List[Alert] = list(result.scalars().all())

    story_rows = _to_story_rows(raw_alerts)
    story = compute_flow_story(sym_upper, story_rows, window_hours=hours)

    return ApiResponse.ok(_story_to_out(story))


# ---------------------------------------------------------------------------
# GET /intelligence/flow-story — Capacity 5 (multi-symbol)
# ---------------------------------------------------------------------------

@router.get("/flow-story", response_model=ApiResponse[FlowStoryListOut])
async def get_flow_stories(
    tenant_id: Optional[uuid.UUID] = Query(None),
    hours: int = Query(8, ge=1, le=72, description="Lookback window in hours"),
    top_n: int = Query(5, ge=1, le=20, description="Top N symbols by alert count"),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate flow stories for the top N most active symbols.

    Symbols are ranked by alert count in the lookback window.
    Useful for an overview dashboard widget or session digest.
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    now = datetime.now(timezone.utc)

    # Find top symbols by alert count in the window
    symbol_count_q = (
        select(Alert.underlying_symbol, func.count(Alert.id).label("cnt"))
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.created_at >= cutoff)
        .group_by(Alert.underlying_symbol)
        .order_by(func.count(Alert.id).desc())
        .limit(top_n)
    )
    sym_result = await db.execute(symbol_count_q)
    top_symbols = [row[0] for row in sym_result.all()]

    if not top_symbols:
        return ApiResponse.ok(
            FlowStoryListOut(
                window_hours=hours,
                symbols_requested=0,
                symbols_with_data=0,
                stories=[],
                computed_at=now,
            )
        )

    # Fetch all alerts for those symbols in the window
    alerts_q = (
        select(Alert)
        .where(Alert.tenant_id == effective_tenant)
        .where(Alert.underlying_symbol.in_(top_symbols))
        .where(Alert.created_at >= cutoff)
        .order_by(Alert.created_at.asc())
        .limit(2000)
    )
    alerts_result = await db.execute(alerts_q)
    all_alerts: List[Alert] = list(alerts_result.scalars().all())

    # Group by symbol and compute story for each
    by_symbol: dict = {s: [] for s in top_symbols}
    for a in all_alerts:
        if a.underlying_symbol in by_symbol:
            by_symbol[a.underlying_symbol].append(a)

    stories = []
    symbols_with_data = 0
    for sym in top_symbols:
        story_rows = _to_story_rows(by_symbol[sym])
        story = compute_flow_story(sym, story_rows, window_hours=hours, now=now)
        if story.total_alerts > 0:
            symbols_with_data += 1
        stories.append(_story_to_out(story))

    return ApiResponse.ok(
        FlowStoryListOut(
            window_hours=hours,
            symbols_requested=len(top_symbols),
            symbols_with_data=symbols_with_data,
            stories=stories,
            computed_at=now,
        )
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _to_story_rows(alerts: List[Alert]) -> List[AlertStoryRow]:
    rows = []
    for a in alerts:
        cf = _parse_contributing_factors(a)
        premium_proxy = cf["notional"]["premium_proxy_usd"] if cf and "notional" in cf else None
        rows.append(
            AlertStoryRow(
                id=str(a.id),
                symbol=a.underlying_symbol,
                expiry=str(a.expiry),
                strike=float(a.strike),
                option_type=a.option_type,
                alert_level=a.alert_level,
                anomaly_score=a.anomaly_score,
                priority_score=getattr(a, "priority_score", None),
                premium_proxy=premium_proxy,
                created_at=a.created_at,
                title=a.title,
            )
        )
    return rows
