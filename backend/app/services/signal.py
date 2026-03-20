"""
Signal engine: compute features and generate alerts from recent normalized snapshots.
Runs after ingestion completes or on its own schedule.

Anomaly score formula (0–10 scale, quality-adjusted):
  raw   = (0.40 × norm_ratio + 0.40 × norm_zscore + 0.20 × norm_voi) × 10
  score = raw × quality_confidence

  norm_ratio  = clamp(volume_ratio / 10, 0, 1)   — saturates at 10× baseline
  norm_zscore = clamp(|z| / 5, 0, 1)             — saturates at z=5
  norm_voi    = clamp(vol/OI / 0.5, 0, 1)        — 0 when OI is unavailable

  quality_confidence starts at 1.0 and is reduced by:
    SCORE_OI_MISSING_PENALTY  if open_interest == 0
    SCORE_SPREAD_WIDE_PENALTY if (ask−bid)/mid > MAX_BID_ASK_SPREAD_PCT
    floored at 0.50 (score never reduced more than 50%)

Alert levels: CRITICAL ≥7 | HIGH ≥5 | MEDIUM ≥3 | LOW ≥1.5

Pre-filters (applied before expensive baseline query):
  1. Zero-price:    mid < $0.02 and last < $0.02
  2. DTE:           expiry > MAX_DTE_DAYS calendar days
  3. Moneyness:     |spot/strike − 1| > MAX_MONEYNESS_PCT
  4. Premium proxy: volume × effective_mid × 100 < MIN_PREMIUM_PROXY
  5. Open interest: open_interest < MIN_OPEN_INTEREST (default 0 = off)

After a successful run, the full breakdown is persisted to
IngestionRun.signal_summary_json for API access and threshold tuning.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, date as date_type
from typing import Dict, List, Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_setup import get_logger
from app.models.models import (
    Alert,
    IngestionRun,
    NormalizedOptionSnapshot,
    SignalFeature,
)
from app.signals.resolver import EffectiveSignalSettings, resolve_signal_settings
from app.intelligence.ranking import build_contributing_factors, compute_priority_score
from app.intelligence.ranking import build_enhanced_explanation
from app.services.dedupe import (
    build_dedupe_key,
    find_active_alert_for_contract,
    should_escalate,
    suppress_duplicate,
    mark_superseded,
)
from app.services.events import EventContext, resolve_event_context

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Signal summary dataclass
# ---------------------------------------------------------------------------

@dataclass
class _SymbolStats:
    contracts_evaluated: int = 0
    features_created: int = 0
    alerts_created: int = 0


@dataclass
class SignalSummary:
    """
    Complete breakdown of one signal engine run.
    Persisted to IngestionRun.signal_summary_json.
    """
    run_id: uuid.UUID
    snapshots_above_min_volume: int = 0
    already_processed: int = 0
    # Pre-filter counts (before baseline DB query)
    filtered_zero_price: int = 0
    filtered_far_expiry: int = 0
    filtered_deep_otm: int = 0
    filtered_low_premium: int = 0
    filtered_low_oi: int = 0
    # Passed all pre-filters → baseline query was executed
    passed_prefilters: int = 0
    # Symbol disabled via signal settings (enabled=False)
    disabled_by_settings: int = 0
    # Baseline guard: feature stored but alert suppressed
    insufficient_baseline: int = 0
    features_created: int = 0
    quality_penalized: int = 0  # features where quality_confidence < 1.0
    alerts_created: int = 0
    # Deduplication counters (008)
    alerts_suppressed: int = 0   # same-key alerts silenced during cooldown
    alerts_escalated: int = 0    # same-contract alerts that upgraded an existing one
    # Error accounting: snapshots where processing raised an exception.
    # Non-zero means the run succeeded partially — some data may be missing.
    snapshots_failed: int = 0
    alert_distribution: Dict[str, int] = field(
        default_factory=lambda: {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    )
    avg_anomaly_score: float = 0.0
    top_symbols: List[dict] = field(default_factory=list)
    thresholds_applied: dict = field(default_factory=dict)
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "snapshots_above_min_volume": self.snapshots_above_min_volume,
            "already_processed": self.already_processed,
            "filtered": {
                "zero_price": self.filtered_zero_price,
                "far_expiry": self.filtered_far_expiry,
                "deep_otm": self.filtered_deep_otm,
                "low_premium": self.filtered_low_premium,
                "low_oi": self.filtered_low_oi,
            },
            "passed_prefilters": self.passed_prefilters,
            "disabled_by_settings": self.disabled_by_settings,
            "insufficient_baseline": self.insufficient_baseline,
            "features_created": self.features_created,
            "quality_penalized": self.quality_penalized,
            "alerts_created": self.alerts_created,
            "alerts_suppressed": self.alerts_suppressed,
            "alerts_escalated": self.alerts_escalated,
            "snapshots_failed": self.snapshots_failed,
            "alert_distribution": self.alert_distribution,
            "avg_anomaly_score": self.avg_anomaly_score,
            "top_symbols": self.top_symbols,
            "thresholds_applied": self.thresholds_applied,
            "elapsed_ms": self.elapsed_ms,
        }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _compute_anomaly_score(
    volume_ratio: float,
    volume_zscore: float,
    volume_oi_ratio: Optional[float],
) -> float:
    """
    Raw weighted anomaly score on a 0–10 scale. Not quality-adjusted.

    Components:
      volume_ratio component  (weight 0.40): saturates at ratio = 10
        — 3× spike contributes 1.2 pts; 10× spike contributes 4.0 pts (max)
      |zscore| component      (weight 0.40): saturates at |z| = 5
        — z=2 contributes 1.6 pts; z=5 contributes 4.0 pts (max)
      volume/OI component     (weight 0.20): saturates at VOI = 0.5
        — VOI=0.25 contributes 1.0 pts; VOI≥0.5 contributes 2.0 pts (max)
        — Contribution is 0 when OI is unavailable (open_interest == 0)
    """
    norm_ratio = _clamp(volume_ratio / 10.0, 0.0, 1.0)
    norm_z = _clamp(abs(volume_zscore) / 5.0, 0.0, 1.0)
    norm_voi = _clamp((volume_oi_ratio or 0.0) / 0.5, 0.0, 1.0)
    raw = 0.40 * norm_ratio + 0.40 * norm_z + 0.20 * norm_voi
    return round(raw * 10.0, 3)


def _alert_level(score: float) -> Optional[str]:
    if score >= settings.ALERT_LEVEL_CRITICAL:
        return "CRITICAL"
    if score >= settings.ALERT_LEVEL_HIGH:
        return "HIGH"
    if score >= settings.ALERT_LEVEL_MEDIUM:
        return "MEDIUM"
    if score >= settings.ALERT_LEVEL_LOW:
        return "LOW"
    return None


def _dte(expiry, as_of: datetime) -> int:
    """
    Calendar days from as_of to expiry. Handles date objects and ISO strings.
    Returns 9999 if expiry cannot be parsed.
    """
    if isinstance(expiry, date_type):
        exp_date = expiry
    else:
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                exp_date = datetime.strptime(str(expiry), fmt).date()
                break
            except ValueError:
                continue
        else:
            return 9999
    as_of_date = as_of.date() if hasattr(as_of, "date") else datetime.now(timezone.utc).date()
    return (exp_date - as_of_date).days


def _build_explanation(
    snap: NormalizedOptionSnapshot,
    feature: SignalFeature,
    level: str,
    dte: int,
    quality_flags: List[str],
    raw_score: float,
    quality_confidence: float,
) -> str:
    otype_word = "call" if snap.option_type == "C" else "put"
    spot = float(snap.spot_price)
    strike = float(snap.strike)
    moneyness = spot / strike if strike > 0 else 1.0
    if moneyness > 1.05:
        money_label = "ITM" if snap.option_type == "C" else "OTM"
    elif moneyness < 0.95:
        money_label = "OTM" if snap.option_type == "C" else "ITM"
    else:
        money_label = "ATM"

    dte_str = f" {dte}DTE" if 0 <= dte <= 9998 else ""
    premium_str = ""
    if feature.premium_proxy is not None:
        premium_str = f" (~${feature.premium_proxy:,.0f} premium proxy)"
    voi_str = ""
    if feature.volume_oi_ratio is not None:
        voi_str = f", VOI {feature.volume_oi_ratio:.2%}"

    lines = [
        f"{level} anomaly: {snap.underlying_symbol} {snap.expiry}{dte_str} "
        f"${strike:.0f} {money_label} {otype_word}.",
        f"Volume {snap.volume:,} vs baseline {feature.baseline_volume:.0f} "
        f"(ratio {feature.volume_ratio:.1f}×, z {feature.volume_zscore:+.1f}{voi_str}){premium_str}.",
    ]
    if snap.implied_vol is not None:
        lines.append(f"IV {snap.implied_vol:.1%}.")

    if quality_confidence < 1.0:
        penalty_pct = round((1.0 - quality_confidence) * 100)
        lines.append(
            f"Score {feature.anomaly_score:.2f}/10 "
            f"[raw {raw_score:.2f}, −{penalty_pct}% quality penalty]."
        )
    else:
        lines.append(f"Score {feature.anomaly_score:.2f}/10.")

    if quality_flags:
        lines.append(f"Quality notes: {', '.join(quality_flags)}.")

    return " ".join(lines)


def _build_title(snap: NormalizedOptionSnapshot, level: str) -> str:
    otype_word = "C" if snap.option_type == "C" else "P"
    return (
        f"[{level}] {snap.underlying_symbol} {snap.expiry} "
        f"${float(snap.strike):.0f}{otype_word} — Vol spike"
    )


# ---------------------------------------------------------------------------
# Baseline computation
# ---------------------------------------------------------------------------

async def _get_baseline_volumes(
    db: AsyncSession,
    symbol: str,
    expiry,
    strike: float,
    option_type: str,
    exclude_run_id: uuid.UUID,
    tenant_id: Optional[uuid.UUID] = None,
) -> List[int]:
    """
    Fetch historical volumes for this (symbol, expiry, strike, option_type)
    from the last BASELINE_LOOKBACK_RUNS ingestion runs (excluding current run).

    Scoped to tenant_id to prevent cross-tenant baseline pollution.
    """
    run_ids_q = (
        select(IngestionRun.id)
        .where(IngestionRun.status == "success")
        .where(IngestionRun.id != exclude_run_id)
        .order_by(IngestionRun.started_at.desc())
        .limit(settings.BASELINE_LOOKBACK_RUNS)
    )
    if tenant_id is not None:
        run_ids_q = run_ids_q.where(IngestionRun.tenant_id == tenant_id)
    run_ids_result = await db.execute(run_ids_q)
    run_ids = list(run_ids_result.scalars().all())

    if not run_ids:
        return []

    volumes_q = (
        select(NormalizedOptionSnapshot.volume)
        .where(NormalizedOptionSnapshot.underlying_symbol == symbol)
        .where(NormalizedOptionSnapshot.expiry == expiry)
        .where(NormalizedOptionSnapshot.strike == strike)
        .where(NormalizedOptionSnapshot.option_type == option_type)
        .where(NormalizedOptionSnapshot.run_id.in_(run_ids))
    )
    result = await db.execute(volumes_q)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Main signal engine entry point
# ---------------------------------------------------------------------------

async def run_signal_engine(
    db: AsyncSession,
    run_id: Optional[uuid.UUID] = None,
    tenant_id: Optional[uuid.UUID] = None,
) -> SignalSummary:
    """
    Compute signal features and generate alerts for snapshots in the given run.
    If run_id is None, uses the most recent successful run (filtered by tenant if provided).

    Persists the full SignalSummary to IngestionRun.signal_summary_json.
    Returns the SignalSummary for the caller's logging.
    """
    _start = time.monotonic()

    if run_id is None:
        latest_q = (
            select(IngestionRun)
            .where(IngestionRun.status == "success")
            .order_by(IngestionRun.started_at.desc())
            .limit(1)
        )
        if tenant_id is not None:
            latest_q = latest_q.where(IngestionRun.tenant_id == tenant_id)
        result = await db.execute(latest_q)
        run = result.scalar_one_or_none()
        if run is None:
            log.warning("signal.no_successful_run")
            return SignalSummary(run_id=uuid.uuid4())  # empty summary
        run_id = run.id

    summary = SignalSummary(
        run_id=run_id,
        thresholds_applied={
            "MIN_VOLUME": settings.MIN_VOLUME,
            "MIN_PREMIUM_PROXY": settings.MIN_PREMIUM_PROXY,
            "MAX_DTE_DAYS": settings.MAX_DTE_DAYS,
            "MAX_MONEYNESS_PCT": settings.MAX_MONEYNESS_PCT,
            "MIN_OPEN_INTEREST": settings.MIN_OPEN_INTEREST,
            "MIN_BASELINE_RUNS_FOR_ALERT": settings.MIN_BASELINE_RUNS_FOR_ALERT,
            "SCORE_OI_MISSING_PENALTY": settings.SCORE_OI_MISSING_PENALTY,
            "SCORE_SPREAD_WIDE_PENALTY": settings.SCORE_SPREAD_WIDE_PENALTY,
            "MAX_BID_ASK_SPREAD_PCT": settings.MAX_BID_ASK_SPREAD_PCT,
        },
    )

    log.info("signal.started", run_id=str(run_id))

    # Load all normalized snapshots for this run that pass the MIN_VOLUME gate
    existing_feature_snap_ids_q = select(SignalFeature.snapshot_id)
    existing_result = await db.execute(existing_feature_snap_ids_q)
    existing_snap_ids = set(existing_result.scalars().all())

    snapshots_q = (
        select(NormalizedOptionSnapshot)
        .where(NormalizedOptionSnapshot.run_id == run_id)
        .where(NormalizedOptionSnapshot.volume >= settings.MIN_VOLUME)
    )
    result = await db.execute(snapshots_q)
    snapshots: List[NormalizedOptionSnapshot] = list(result.scalars().all())
    summary.snapshots_above_min_volume = len(snapshots)

    existing_alert_snap_ids_q = select(Alert.snapshot_id)
    alert_result = await db.execute(existing_alert_snap_ids_q)
    existing_alert_snap_ids = set(alert_result.scalars().all())

    # Pre-resolve effective signal settings for each unique symbol in this batch.
    # This issues at most 2 DB queries per symbol (symbol override + tenant defaults)
    # before the main loop, rather than inside it.
    unique_symbols = {
        snap.underlying_symbol
        for snap in snapshots
        if snap.id not in existing_snap_ids
    }
    sym_cfg: Dict[str, EffectiveSignalSettings] = {}
    for sym_name in unique_symbols:
        sym_cfg[sym_name] = await resolve_signal_settings(db, tenant_id, sym_name)

    # Per-symbol tracking for top_symbols summary
    symbol_stats: Dict[str, _SymbolStats] = {}

    scores_accumulated: List[float] = []

    # Per-symbol event context cache — populated lazily on first alert candidate
    # for each symbol.  Avoids querying the events table for snapshots that never
    # reach the alert path (filtered, below baseline, etc.).
    event_ctx_cache: Dict[str, Optional[EventContext]] = {}
    today = datetime.now(timezone.utc).date()

    for snap in snapshots:
        if snap.id in existing_snap_ids:
            summary.already_processed += 1
            continue

        sym = snap.underlying_symbol
        if sym not in symbol_stats:
            symbol_stats[sym] = _SymbolStats()

        # Effective settings for this symbol (resolver guarantees non-null values)
        eff = sym_cfg.get(sym)

        # Signals disabled for this symbol via tenant/symbol settings
        if eff is not None and not eff.enabled:
            summary.disabled_by_settings += 1
            log.debug(
                "signal.skipped_disabled",
                symbol=sym,
                tenant_id=str(tenant_id) if tenant_id else None,
            )
            continue

        # ── Per-snapshot savepoint ────────────────────────────────────────────
        # Create a nested transaction before touching DB state for this snapshot.
        # If something fails later, roll back the session to recover from the
        # aborted transaction state and continue with the next snapshot.
        _snap_sp = await db.begin_nested()
        try:
            # ----------------------------------------------------------------
            # PRE-FILTERS — cheap local checks before the baseline DB query.
            # Use per-symbol effective config where available, fall back to
            # global settings if resolver returned nothing.
            # ----------------------------------------------------------------

            mid_price = (float(snap.bid) + float(snap.ask)) / 2.0
            current_vol = float(snap.volume)
            effective_price = mid_price if mid_price > 0.01 else float(snap.last)

            eff_max_dte = eff.max_dte_days if eff else settings.MAX_DTE_DAYS
            eff_max_mono = eff.max_moneyness_pct if eff else settings.MAX_MONEYNESS_PCT
            eff_min_premium = eff.min_premium_proxy if eff else settings.MIN_PREMIUM_PROXY
            eff_min_oi = eff.min_open_interest if eff else settings.MIN_OPEN_INTEREST

            # 1. Zero-price guard
            if mid_price < 0.02 and float(snap.last) < 0.02:
                summary.filtered_zero_price += 1
                log.debug(
                    "signal.filtered_zero_price",
                    snapshot_id=str(snap.id),
                    symbol=sym,
                    bid=str(snap.bid),
                    ask=str(snap.ask),
                    last=str(snap.last),
                )
                continue

            # 2. DTE filter
            dte = _dte(snap.expiry, snap.as_of_ts)
            if dte > eff_max_dte:
                summary.filtered_far_expiry += 1
                log.debug(
                    "signal.filtered_far_expiry",
                    snapshot_id=str(snap.id),
                    symbol=sym,
                    expiry=str(snap.expiry),
                    dte=dte,
                    max_dte=eff_max_dte,
                )
                continue

            # 3. Moneyness filter
            spot = float(snap.spot_price)
            strike = float(snap.strike)
            if spot > 0 and strike > 0:
                moneyness_dist = abs(spot / strike - 1.0)
                if moneyness_dist > eff_max_mono:
                    summary.filtered_deep_otm += 1
                    log.debug(
                        "signal.filtered_deep_otm",
                        snapshot_id=str(snap.id),
                        symbol=sym,
                        spot=spot,
                        strike=strike,
                        moneyness_dist=round(moneyness_dist, 4),
                        max_moneyness=eff_max_mono,
                    )
                    continue

            # 4. Premium proxy filter
            if eff_min_premium > 0:
                raw_premium = current_vol * effective_price * 100.0
                if raw_premium < eff_min_premium:
                    summary.filtered_low_premium += 1
                    log.debug(
                        "signal.filtered_low_premium",
                        snapshot_id=str(snap.id),
                        symbol=sym,
                        premium=round(raw_premium, 2),
                        min_premium=eff_min_premium,
                    )
                    continue

            # 5. Min open interest
            if snap.open_interest < eff_min_oi:
                summary.filtered_low_oi += 1
                log.debug(
                    "signal.filtered_low_oi",
                    snapshot_id=str(snap.id),
                    symbol=sym,
                    oi=snap.open_interest,
                    min_oi=eff_min_oi,
                )
                continue

            summary.passed_prefilters += 1
            symbol_stats[sym].contracts_evaluated += 1

            # ----------------------------------------------------------------
            # BASELINE QUERY
            # ----------------------------------------------------------------

            hist_vols = await _get_baseline_volumes(
                db,
                symbol=sym,
                expiry=snap.expiry,
                strike=float(snap.strike),
                option_type=snap.option_type,
                exclude_run_id=run_id,
                tenant_id=tenant_id,
            )

            if len(hist_vols) >= 3:
                hist_arr = np.array(hist_vols, dtype=float)
                baseline_volume = float(np.mean(hist_arr))
                baseline_std = float(np.std(hist_arr, ddof=1))
            else:
                # Fallback floor — alerts suppressed until MIN_BASELINE_RUNS_FOR_ALERT
                baseline_volume = max(50.0, float(snap.open_interest) * 0.02)
                baseline_std = baseline_volume * 0.5

            volume_ratio = current_vol / max(baseline_volume, 1.0)
            if baseline_std > 0:
                volume_zscore = (current_vol - baseline_volume) / baseline_std
            else:
                volume_zscore = (current_vol - baseline_volume) / max(baseline_volume, 1.0)

            volume_oi_ratio: Optional[float] = None
            if snap.open_interest > 0:
                volume_oi_ratio = current_vol / float(snap.open_interest)

            premium_proxy = current_vol * effective_price * 100.0

            # ----------------------------------------------------------------
            # QUALITY CONFIDENCE
            # ----------------------------------------------------------------

            quality_flags: List[str] = []
            quality_confidence = 1.0

            if snap.open_interest == 0:
                quality_flags.append("OI unavailable")
                quality_confidence -= settings.SCORE_OI_MISSING_PENALTY

            if mid_price >= 0.05:
                spread_pct = (float(snap.ask) - float(snap.bid)) / mid_price
                if spread_pct > settings.MAX_BID_ASK_SPREAD_PCT:
                    quality_flags.append(f"wide spread ({spread_pct:.0%})")
                    quality_confidence -= settings.SCORE_SPREAD_WIDE_PENALTY

            quality_confidence = max(0.50, quality_confidence)

            # ----------------------------------------------------------------
            # SCORE COMPUTATION
            # ----------------------------------------------------------------

            raw_score = _compute_anomaly_score(volume_ratio, volume_zscore, volume_oi_ratio)
            anomaly_score = round(raw_score * quality_confidence, 3)

            if quality_confidence < 1.0:
                summary.quality_penalized += 1

            feature = SignalFeature(
                snapshot_id=snap.id,
                baseline_volume=baseline_volume,
                volume_ratio=volume_ratio,
                volume_zscore=volume_zscore,
                volume_oi_ratio=volume_oi_ratio,
                premium_proxy=premium_proxy,
                iv_change=None,
                anomaly_score=anomaly_score,
                raw_anomaly_score=raw_score,
                quality_confidence=quality_confidence,
            )
            db.add(feature)
            summary.features_created += 1
            symbol_stats[sym].features_created += 1
            scores_accumulated.append(anomaly_score)

            # ----------------------------------------------------------------
            # BASELINE SUFFICIENCY GUARD
            # ----------------------------------------------------------------

            sufficient_baseline = len(hist_vols) >= settings.MIN_BASELINE_RUNS_FOR_ALERT
            if not sufficient_baseline:
                summary.insufficient_baseline += 1
                log.info(
                    "signal.skipped_alert_insufficient_baseline",
                    snapshot_id=str(snap.id),
                    symbol=sym,
                    hist_vols_count=len(hist_vols),
                    required=settings.MIN_BASELINE_RUNS_FOR_ALERT,
                    anomaly_score=anomaly_score,
                )

            level = _alert_level(anomaly_score)

            # Per-symbol minimum alert level: suppress if level is below the
            # configured minimum (e.g. min_alert_level="HIGH" mutes LOW/MEDIUM).
            if level is not None and eff is not None and not eff.alert_level_passes(level):
                log.debug(
                    "signal.skipped_below_min_alert_level",
                    symbol=sym,
                    level=level,
                    min_alert_level=eff.min_alert_level,
                )
                level = None  # suppressed — feature is still stored

            if level is not None and snap.id not in existing_alert_snap_ids and sufficient_baseline:
                # Build structured contributing factors (Capacity 4 — Actionable Explanations)
                contributing_factors = build_contributing_factors(
                    volume_ratio=volume_ratio,
                    volume_zscore=volume_zscore,
                    baseline_volume=baseline_volume,
                    current_volume=int(current_vol),
                    premium_proxy=premium_proxy,
                    dte=dte,
                    quality_confidence=quality_confidence,
                    quality_flags=quality_flags,
                    spot=float(snap.spot_price),
                    strike=float(snap.strike),
                    option_type=snap.option_type,
                    iv=snap.implied_vol,
                    data_source=snap.source,
                )

                # Enhanced explanation using structured factors (Capacity 4)
                explanation = build_enhanced_explanation(
                    symbol=sym,
                    expiry=str(snap.expiry),
                    strike=float(snap.strike),
                    option_type=snap.option_type,
                    factors=contributing_factors,
                    alert_level=level,
                    anomaly_score=anomaly_score,
                    raw_score=raw_score,
                    quality_confidence=quality_confidence,
                )

                title = _build_title(snap, level)

                # ── Event catalyst context (009) ──────────────────────────────
                # Resolve once per symbol per run, cached for the rest of the loop.
                if sym not in event_ctx_cache:
                    event_ctx_cache[sym] = await resolve_event_context(
                        db, sym, tenant_id, today
                    )
                event_ctx = event_ctx_cache[sym]

                # Inject catalyst section into contributing_factors so it appears
                # in alert detail views and the flow story context.
                if event_ctx:
                    contributing_factors["catalyst"] = {
                        "event_type": event_ctx.next_event_type,
                        "event_date": str(event_ctx.next_event_date),
                        "days_to_event": event_ctx.days_to_event,
                        "context": event_ctx.catalyst_context,
                        "boost_applied": event_ctx.catalyst_boost if event_ctx.is_near else 1.0,
                    }

                # Compute intrinsic priority score (Capacity 1 — Smart Flow Ranking)
                priority_score = compute_priority_score(
                    anomaly_score=anomaly_score,
                    premium_proxy=premium_proxy,
                    quality_confidence=quality_confidence,
                    priority_weight=eff.priority_weight if eff else 1.0,
                )

                # Apply catalyst boost when a high-impact event is near.
                # Boost is applied before priority gates so event-adjacent signals
                # can cross the HIGH/CRITICAL threshold they would otherwise miss.
                if event_ctx and event_ctx.is_near and priority_score is not None:
                    priority_score = min(10.0, round(priority_score * event_ctx.catalyst_boost, 3))

                # ── Priority gates: HIGH/CRITICAL require minimum priority score ─
                # Guards against low-quality or low-notional contracts reaching
                # elevated levels on anomaly score alone.
                ps = priority_score or 0.0
                if level == "CRITICAL" and ps < settings.MIN_PRIORITY_SCORE_CRITICAL:
                    log.debug(
                        "signal.suppressed_priority_gate",
                        symbol=sym,
                        level=level,
                        priority_score=ps,
                        required=settings.MIN_PRIORITY_SCORE_CRITICAL,
                    )
                    level = None
                elif level == "HIGH" and ps < settings.MIN_PRIORITY_SCORE_HIGH:
                    log.debug(
                        "signal.suppressed_priority_gate",
                        symbol=sym,
                        level=level,
                        priority_score=ps,
                        required=settings.MIN_PRIORITY_SCORE_HIGH,
                    )
                    level = None

                if level is None:
                    continue

                # ── Deduplication / cooldown ──────────────────────────────────
                # Contract-level check: one active alert per (contract, cooldown window).
                # Handles both same-level duplicates and cross-level drift — e.g. a
                # MEDIUM that drifts to LOW score is absorbed into the MEDIUM, not
                # filed as a separate LOW alert.
                now = datetime.now(timezone.utc)
                cooldown_minutes = eff.cooldown_window_minutes if eff else settings.ALERT_COOLDOWN_MINUTES

                dedupe_key = build_dedupe_key(
                    tenant_id=tenant_id,
                    symbol=sym,
                    expiry=snap.expiry,
                    strike=snap.strike,
                    option_type=snap.option_type,
                    alert_level=level,
                )

                predecessor_id = None
                if cooldown_minutes > 0:
                    contract_alert = await find_active_alert_for_contract(
                        db, tenant_id, sym, snap.expiry, snap.strike, snap.option_type, now
                    )
                    if contract_alert is not None:
                        if should_escalate(contract_alert, level, priority_score):
                            # Genuine level upgrade or significant score jump
                            mark_superseded(contract_alert)
                            predecessor_id = contract_alert.id
                            summary.alerts_escalated += 1
                            log.info(
                                "signal.alert_escalated",
                                superseded_id=str(predecessor_id),
                                new_level=level,
                                old_level=contract_alert.alert_level,
                                symbol=sym,
                            )
                        else:
                            # Same or lower level within cooldown — absorb silently
                            suppress_duplicate(contract_alert, now, cooldown_minutes)
                            summary.alerts_suppressed += 1
                            log.debug(
                                "signal.alert_suppressed",
                                canonical_id=str(contract_alert.id),
                                symbol=sym,
                                new_level=level,
                                existing_level=contract_alert.alert_level,
                            )
                            continue

                alert = Alert(
                    snapshot_id=snap.id,
                    tenant_id=tenant_id,
                    underlying_symbol=sym,
                    expiry=snap.expiry,
                    strike=snap.strike,
                    option_type=snap.option_type,
                    as_of_ts=snap.as_of_ts,
                    alert_level=level,
                    anomaly_score=anomaly_score,
                    raw_anomaly_score=raw_score,
                    quality_confidence=quality_confidence,
                    quality_flags=json.dumps(quality_flags) if quality_flags else None,
                    dte_at_alert=dte,
                    title=title,
                    explanation=explanation,
                    priority_score=priority_score,
                    contributing_factors_json=contributing_factors,
                    status="active",
                    # Deduplication fields
                    dedupe_key=dedupe_key,
                    duplicate_count=0,
                    escalated_from_alert_id=predecessor_id,
                    cooldown_expires_at=(
                        now + timedelta(minutes=cooldown_minutes)
                        if cooldown_minutes > 0 else None
                    ),
                    # Event catalyst context — snapshot at alert creation time
                    catalyst_context=event_ctx.catalyst_context if event_ctx else None,
                    days_to_event=event_ctx.days_to_event if event_ctx else None,
                    next_event_type=event_ctx.next_event_type if event_ctx else None,
                    next_event_date=event_ctx.next_event_date if event_ctx else None,
                )
                db.add(alert)
                summary.alerts_created += 1
                summary.alert_distribution[level] = summary.alert_distribution.get(level, 0) + 1
                symbol_stats[sym].alerts_created += 1

        except Exception as exc:
            try:
                await _snap_sp.rollback()
            except Exception as rb_exc:
                log.error(
                    "signal.savepoint_rollback_failed",
                    snapshot_id=str(snap.id),
                    symbol=sym,
                    rollback_error=str(rb_exc),
                    exc_info=True,
                )
                raise

            summary.snapshots_failed += 1
            log.warning(
                "signal.snapshot_failed_recovered",
                snapshot_id=str(snap.id),
                symbol=sym,
                error=str(exc),
                exc_info=True,
            )
            continue

    # Finalize summary stats
    summary.avg_anomaly_score = round(
        float(np.mean(scores_accumulated)) if scores_accumulated else 0.0, 3
    )
    summary.top_symbols = sorted(
        [
            {
                "symbol": sym,
                "contracts_evaluated": st.contracts_evaluated,
                "features": st.features_created,
                "alerts": st.alerts_created,
            }
            for sym, st in symbol_stats.items()
        ],
        key=lambda x: x["alerts"],
        reverse=True,
    )[:10]

    summary.elapsed_ms = round((time.monotonic() - _start) * 1000)

    # ── Partial-run warning ───────────────────────────────────────────────────
    if summary.snapshots_failed > 0:
        log.warning(
            "signal.run_partial",
            run_id=str(run_id),
            snapshots_failed=summary.snapshots_failed,
            snapshots_evaluated=summary.snapshots_above_min_volume,
            msg=(
                f"{summary.snapshots_failed} snapshot(s) failed and were skipped. "
                "Features and alerts for those contracts are missing from this run. "
                "Check signal.snapshot_failed_recovered log entries for details."
            ),
        )

    # ── Persist summary to the run record ────────────────────────────────────
    # This runs AFTER all per-snapshot savepoints have been committed or rolled
    # back, so the outer transaction is always in a clean state here.
    try:
        run_result = await db.execute(select(IngestionRun).where(IngestionRun.id == run_id))
        run_obj = run_result.scalar_one_or_none()
        if run_obj is not None:
            run_obj.signal_summary_json = summary.to_dict()
            log.debug("signal.summary_staged", run_id=str(run_id))
        else:
            log.warning("signal.summary_run_not_found", run_id=str(run_id))
    except Exception as exc:
        # Non-fatal: the features and alerts are still valid; only the
        # signal_summary_json field on the run record would be missing.
        log.warning(
            "signal.summary_persist_failed",
            run_id=str(run_id),
            error=str(exc),
            exc_info=True,
        )

    # ── Final commit ─────────────────────────────────────────────────────────
    try:
        await db.commit()
        log.debug("signal.committed", run_id=str(run_id))
    except Exception as exc:
        log.exception(
            "signal.commit_failed",
            run_id=str(run_id),
            error=str(exc),
        )
        await db.rollback()
        return summary

    # ── Final log ─────────────────────────────────────────────────────────────
    log.info(
        "signal.finished",
        run_id=str(run_id),
        snapshots_evaluated=summary.snapshots_above_min_volume,
        passed_prefilters=summary.passed_prefilters,
        disabled_by_settings=summary.disabled_by_settings,
        features=summary.features_created,
        alerts=summary.alerts_created,
        alerts_suppressed=summary.alerts_suppressed,
        alerts_escalated=summary.alerts_escalated,
        snapshots_failed=summary.snapshots_failed,
        quality_penalized=summary.quality_penalized,
        insufficient_baseline=summary.insufficient_baseline,
        filtered_zero_price=summary.filtered_zero_price,
        filtered_far_expiry=summary.filtered_far_expiry,
        filtered_deep_otm=summary.filtered_deep_otm,
        filtered_low_premium=summary.filtered_low_premium,
        filtered_low_oi=summary.filtered_low_oi,
        elapsed_ms=summary.elapsed_ms,
    )
    return summary
