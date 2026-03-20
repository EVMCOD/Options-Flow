"""
Provider diagnostics endpoints.

GET  /diagnostics/provider/{config_id}              — effective (non-secret) config view
POST /diagnostics/provider/{config_id}/test-fetch   — synchronous provider probe

These endpoints are for operational validation and troubleshooting.
They do NOT store any data and do NOT trigger ingestion runs.
Credentials (credentials_json) are never exposed in any response.

Note on latency: test-fetch is synchronous. For IBKR, each symbol requires
a fresh TCP connection to TWS/IB Gateway — budget 30–60 s per symbol.
Keep max_symbols ≤ 3 for interactive use.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging_setup import get_logger
from app.models.models import IngestionRun, ScannerUniverse
from app.schemas.schemas import (
    ApiResponse,
    FilterTuningNote,
    ProviderTestReport,
    RunSignalSummary,
    ThresholdReview,
)
from app.services.diagnostics import run_provider_test
from app.tenants.service import get_provider_config_by_id, get_tenant_by_id

log = get_logger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_config(config_id: uuid.UUID, db: AsyncSession):
    """Load and return a provider config, raising 404 if absent."""
    cfg = await get_provider_config_by_id(db, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Provider config not found")
    return cfg


async def _get_universe_symbols(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    max_symbols: int,
) -> List[str]:
    """Return up to max_symbols enabled symbols from the tenant's universe."""
    result = await db.execute(
        select(ScannerUniverse.symbol)
        .where(ScannerUniverse.tenant_id == tenant_id)
        .where(ScannerUniverse.enabled == True)
        .order_by(ScannerUniverse.priority.desc(), ScannerUniverse.created_at.asc())
        .limit(max_symbols)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/provider/{config_id}",
    response_model=ApiResponse[dict],
)
async def get_provider_config_info(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Return effective (non-sensitive) configuration for a provider config.

    Shows config_json, operational metadata (is_active, is_default, status,
    last_healthy_at, last_error) and the market_data_mode that would be used
    for this provider instance.

    credentials_json is intentionally excluded from the response.
    """
    cfg = await _resolve_config(config_id, db)

    from app.providers.registry import ProviderRegistry

    # Build a temporary provider instance just to get market_data_mode —
    # ProviderCredentials wrapper ensures credentials never leak to repr/str.
    try:
        provider = ProviderRegistry.resolve(cfg)
        mdm = provider.market_data_mode()
    except Exception:
        mdm = None

    return ApiResponse.ok(
        {
            "config_id": str(cfg.id),
            "tenant_id": str(cfg.tenant_id),
            "provider_type": cfg.provider_type,
            "is_active": cfg.is_active,
            "is_default": cfg.is_default,
            "status": cfg.status,
            "last_healthy_at": cfg.last_healthy_at.isoformat() if cfg.last_healthy_at else None,
            "last_error": cfg.last_error,
            "market_data_mode": mdm,
            "config_json": cfg.config_json or {},
            # credentials_json: intentionally omitted
        }
    )


@router.post(
    "/provider/{config_id}/test-fetch",
    response_model=ApiResponse[ProviderTestReport],
)
async def test_provider_fetch(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    symbols: Optional[str] = Query(
        None,
        description=(
            "Comma-separated symbols to test, e.g. 'SPY,QQQ'. "
            "If omitted, uses the first max_symbols from the tenant's universe."
        ),
    ),
    max_symbols: int = Query(
        2,
        ge=1,
        le=5,
        description=(
            "Max symbols to test when symbols param is not provided. "
            "Keep ≤ 3 for IBKR (30–60 s per symbol)."
        ),
    ),
):
    """
    Run a diagnostic test fetch against a provider config.

    Calls fetch_chain() for each requested symbol and returns a rich quality
    report including:
    - Connection result
    - Contracts returned per symbol
    - Null field rates (volume, OI, IV, bid/ask)
    - Sample contracts (up to 3 per symbol, highest volume first)
    - Overall quality verdict: poor | limited | usable | good
    - Plain-language quality notes

    IMPORTANT: This endpoint is synchronous. For IBKR delayed:
    - Each symbol requires a fresh TCP connection + options chain request.
    - Budget 30–60 seconds per symbol.
    - Keep max_symbols ≤ 2 for interactive use.

    Nothing is stored. No ingestion run is created. No side effects.
    Credentials are never included in the response.
    """
    cfg = await _resolve_config(config_id, db)

    # Resolve which symbols to test
    if symbols:
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:max_symbols]
    else:
        symbol_list = await _get_universe_symbols(db, cfg.tenant_id, max_symbols)

    if not symbol_list:
        raise HTTPException(
            status_code=422,
            detail=(
                "No symbols to test. Either pass ?symbols=SPY,QQQ or ensure "
                "the tenant has enabled symbols in their universe."
            ),
        )

    log.info(
        "diagnostics.test_fetch_started",
        config_id=str(config_id),
        provider_type=cfg.provider_type,
        symbols=symbol_list,
    )

    report = await run_provider_test(config=cfg, symbols=symbol_list)

    log.info(
        "diagnostics.test_fetch_complete",
        config_id=str(config_id),
        provider_type=cfg.provider_type,
        verdict=report.quality_verdict,
        elapsed_ms=report.elapsed_ms,
        symbols_with_data=report.symbols_with_data,
        total_contracts=report.total_contracts_returned,
    )

    return ApiResponse.ok(report)


# ---------------------------------------------------------------------------
# Threshold tuning review
# ---------------------------------------------------------------------------

_FILTER_HIGH_RATE = 0.35   # filter removing > 35% → may be too aggressive
_FILTER_LOW_RATE = 0.02    # filter removing < 2% → minimal impact, consider tightening
_ALERT_RATE_HIGH = 0.30    # > 30% of features become alerts → threshold too low
_ALERT_RATE_LOW = 0.03     # < 3% → threshold too high or baseline not warmed up
_BASELINE_GUARD_HIGH = 0.50  # > 50% of passed features suppressed for baseline


@router.get(
    "/threshold-review",
    response_model=ApiResponse[ThresholdReview],
)
async def threshold_review(
    tenant_id: Optional[uuid.UUID] = Query(
        None,
        description="Tenant to analyze. Defaults to the system default tenant.",
    ),
    lookback_runs: int = Query(
        10,
        ge=2,
        le=50,
        description="Number of recent successful runs to analyze.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Heuristic analysis of recent signal engine runs to surface miscalibrated thresholds.

    For each pre-filter, computes the average removal rate across recent runs and
    flags it if the rate is unusually high (too aggressive) or unusually low (too lax).
    Also checks the alert rate, baseline sufficiency rate, and quality penalty rate.

    This does NOT change any settings — it is read-only analysis for human review.
    Only runs with signal_summary_json populated are included (migration 005+).
    """
    effective_tenant = tenant_id or _DEFAULT_TENANT

    result = await db.execute(
        select(IngestionRun)
        .where(IngestionRun.tenant_id == effective_tenant)
        .where(IngestionRun.status == "success")
        .where(IngestionRun.signal_summary_json.isnot(None))
        .order_by(IngestionRun.started_at.desc())
        .limit(lookback_runs)
    )
    runs = list(result.scalars().all())

    if not runs:
        return ApiResponse.ok(
            ThresholdReview(
                runs_analyzed=0,
                lookback_runs=lookback_runs,
                filter_notes=[],
                alert_rate_note="No runs with signal_summary_json found. Run the scanner first.",
                baseline_note=None,
                general_notes=[
                    "No data available. Runs before migration 005 don't have signal summaries."
                ],
            )
        )

    summaries = [RunSignalSummary.from_json(r.signal_summary_json) for r in runs]
    summaries = [s for s in summaries if s is not None]

    if not summaries:
        return ApiResponse.ok(
            ThresholdReview(
                runs_analyzed=0,
                lookback_runs=lookback_runs,
                filter_notes=[],
                alert_rate_note=None,
                baseline_note=None,
                general_notes=["Could not parse signal summaries from recent runs."],
            )
        )

    def _avg(values):
        return sum(values) / len(values) if values else 0.0

    # Per-filter average removal rates
    total_list = [s.snapshots_above_min_volume for s in summaries]
    avg_total = _avg(total_list)

    def _filter_rate(getter) -> float:
        rates = []
        for s, total in zip(summaries, total_list):
            if total > 0:
                rates.append(getter(s) / total)
        return _avg(rates)

    filter_configs = [
        (
            "zero_price",
            "hardcoded",
            "mid < $0.02 and last < $0.02",
            lambda s: s.filtered.zero_price,
        ),
        (
            "far_expiry",
            "MAX_DTE_DAYS",
            settings.MAX_DTE_DAYS,
            lambda s: s.filtered.far_expiry,
        ),
        (
            "deep_otm",
            "MAX_MONEYNESS_PCT",
            settings.MAX_MONEYNESS_PCT,
            lambda s: s.filtered.deep_otm,
        ),
        (
            "low_premium",
            "MIN_PREMIUM_PROXY",
            settings.MIN_PREMIUM_PROXY,
            lambda s: s.filtered.low_premium,
        ),
        (
            "low_oi",
            "MIN_OPEN_INTEREST",
            settings.MIN_OPEN_INTEREST,
            lambda s: s.filtered.low_oi,
        ),
    ]

    filter_notes: List[FilterTuningNote] = []
    for filter_name, setting_name, current_val, getter in filter_configs:
        rate = _filter_rate(getter)
        recommendation = None
        if rate > _FILTER_HIGH_RATE:
            recommendation = (
                f"Removing {rate:.0%} of evaluated contracts — may be too aggressive. "
                f"Consider raising {setting_name} to pass more contracts."
            )
        elif rate < _FILTER_LOW_RATE and filter_name not in ("zero_price", "low_oi"):
            recommendation = (
                f"Removing only {rate:.0%} of contracts — minimal impact. "
                f"Consider tightening {setting_name} to reduce noise."
            )
        filter_notes.append(
            FilterTuningNote(
                filter_name=filter_name,
                setting=str(setting_name),
                current_value=current_val,
                avg_removal_rate=round(rate, 4),
                recommendation=recommendation,
            )
        )

    # Alert rate note
    avg_features = _avg([s.features_created for s in summaries])
    avg_alerts = _avg([s.alerts_created for s in summaries])
    alert_rate = avg_alerts / avg_features if avg_features > 0 else 0.0
    alert_rate_note: Optional[str] = None
    if alert_rate > _ALERT_RATE_HIGH:
        alert_rate_note = (
            f"Alert rate is {alert_rate:.0%} (alerts/features) — very high. "
            "Alert thresholds may be too low, or the baseline hasn't warmed up yet. "
            "Consider raising MIN_BASELINE_RUNS_FOR_ALERT or alert score thresholds."
        )
    elif alert_rate < _ALERT_RATE_LOW and avg_features > 5:
        alert_rate_note = (
            f"Alert rate is {alert_rate:.0%} — very low. "
            "Either thresholds are too high, volume spikes are genuinely absent, "
            "or the baseline is not warmed up. Check insufficient_baseline counts."
        )
    else:
        alert_rate_note = f"Alert rate is {alert_rate:.0%} of features — within expected range."

    # Baseline sufficiency note
    avg_passed = _avg([s.passed_prefilters for s in summaries])
    avg_suppressed = _avg([s.insufficient_baseline for s in summaries])
    baseline_note: Optional[str] = None
    if avg_passed > 0:
        suppression_rate = avg_suppressed / avg_passed
        if suppression_rate > _BASELINE_GUARD_HIGH:
            baseline_note = (
                f"{suppression_rate:.0%} of processed contracts have insufficient baseline data. "
                "Most alerts are suppressed. Run the scanner more to build up baseline history. "
                f"Need {settings.MIN_BASELINE_RUNS_FOR_ALERT} measured runs per contract."
            )
        else:
            baseline_note = (
                f"{suppression_rate:.0%} of processed contracts suppressed for insufficient baseline — normal."
            )

    # Quality penalty note
    avg_penalized = _avg([s.quality_penalized for s in summaries])
    quality_rate = avg_penalized / avg_features if avg_features > 0 else 0.0
    general_notes = []
    if quality_rate > 0.70:
        general_notes.append(
            f"{quality_rate:.0%} of features have quality penalties (missing OI or wide spread). "
            "This is expected with IBKR delayed data. If OI becomes available, "
            "reduce SCORE_OI_MISSING_PENALTY or clear it entirely."
        )

    avg_score = _avg([s.avg_anomaly_score for s in summaries])
    general_notes.append(
        f"Avg anomaly score across {len(summaries)} runs: {avg_score:.2f}/10. "
        "Healthy range for delayed data: 2.0–4.5."
    )

    return ApiResponse.ok(
        ThresholdReview(
            runs_analyzed=len(summaries),
            lookback_runs=lookback_runs,
            filter_notes=filter_notes,
            alert_rate_note=alert_rate_note,
            baseline_note=baseline_note,
            general_notes=general_notes,
        )
    )
