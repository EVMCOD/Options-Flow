"""
Alert deduplication and cooldown service.

Deduplication strategy
─────────────────────
Every alert carries a `dedupe_key` that uniquely identifies its
(tenant, contract, level) combination:

    {tenant_id}:{symbol}:{expiry}:{strike}:{option_type}:{alert_level}

When a new alert would fire, the engine first checks for an existing
*active* alert with the same key whose cooldown has not yet expired.
Three outcomes are possible:

  1. No active duplicate found  → create the alert normally.
  2. Active duplicate found, same level  → suppress (increment duplicate_count,
     extend cooldown, update last_seen_at on the existing alert).
  3. Active duplicate found, new level is strictly higher (escalation)  →
     mark the old alert as "superseded", create the new one and link back via
     `escalated_from_alert_id`.  Priority-score escalation (>20% improvement
     at the same level) also triggers this path.

Cooldown window
───────────────
The default cooldown is controlled by `settings.ALERT_COOLDOWN_MINUTES`.
It can be overridden per tenant (`TenantSignalSettings.cooldown_window_minutes`)
or per symbol (`TenantSymbolSettings.cooldown_window_minutes`), with the symbol
override taking highest precedence.

Each suppressed duplicate *extends* the cooldown from the moment it was seen,
so a contract that continuously fires does not flood the feed.

Pattern type
────────────
When an intelligence-layer pattern is detected (e.g. repeated_prints,
strike_cluster), the pattern name is appended to the dedupe key:

    {tenant_id}:{symbol}:{expiry}:{strike}:{option_type}:{level}:{pattern}

Pattern-first behaviour: a single pattern-level alert suppresses the
individual-print alerts that would otherwise fire for the same contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_setup import get_logger
from app.models.models import Alert

log = get_logger(__name__)

# Level ordering used for escalation comparison.
_LEVEL_ORDER: dict[str, int] = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}

# Minimum priority-score improvement fraction to trigger an escalation at the
# same alert level (e.g., 0.20 = 20% better score required).
_ESCALATION_SCORE_THRESHOLD = 0.20


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------

def build_dedupe_key(
    tenant_id: Optional[uuid.UUID],
    symbol: str,
    expiry: object,  # date | str
    strike: Decimal | float,
    option_type: str,
    alert_level: str,
    pattern_type: Optional[str] = None,
) -> str:
    """
    Build the canonical deduplication key for a (tenant, contract, level) tuple.

    The key is a colon-separated string — opaque to callers, deterministic
    for the same inputs.  Includes the tenant so cross-tenant leakage is
    structurally impossible.

    Args:
        tenant_id: UUID of the owning tenant, or None for the global default.
        symbol: Underlying symbol, e.g. "SPY".
        expiry: Contract expiry as a date object or ISO string.
        strike: Strike price.
        option_type: "C" or "P".
        alert_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL".
        pattern_type: Optional pattern name (e.g. "repeated_prints").  When
            provided, it is appended to the key so that pattern-summarised
            alerts are deduped separately from raw-print alerts.
    """
    tid = str(tenant_id) if tenant_id is not None else "global"
    expiry_str = expiry.isoformat() if hasattr(expiry, "isoformat") else str(expiry)
    strike_str = f"{float(strike):.2f}"
    key = f"{tid}:{symbol.upper()}:{expiry_str}:{strike_str}:{option_type.upper()}:{alert_level.upper()}"
    if pattern_type:
        key += f":{pattern_type}"
    return key


# ---------------------------------------------------------------------------
# Cooldown lookups
# ---------------------------------------------------------------------------

async def find_active_duplicate(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    dedupe_key: str,
    now: datetime,
) -> Optional[Alert]:
    """
    Return the most-recently-created active alert with the given dedupe_key
    whose cooldown window has not yet expired.

    Returns None when:
    - No alert with this key exists.
    - All matching alerts have status != "active".
    - All matching alerts have cooldown_expires_at <= now (cooldown over).
    """
    q = (
        select(Alert)
        .where(
            and_(
                Alert.tenant_id == tenant_id,
                Alert.dedupe_key == dedupe_key,
                Alert.status == "active",
                Alert.cooldown_expires_at > now,
            )
        )
        .order_by(Alert.created_at.desc())
        .limit(1)
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def find_active_alert_for_contract(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    symbol: str,
    expiry: object,
    strike: Decimal | float,
    option_type: str,
    now: datetime,
) -> Optional[Alert]:
    """
    Find the highest-level active alert for this contract (any alert level)
    whose cooldown has not expired.

    This is the primary deduplication gate: one active alert per contract per
    cooldown window.  By searching across all levels we prevent a MEDIUM alert
    from coexisting with a LOW alert for the same contract when the score drifts
    slightly between runs.

    The result is ordered so that a higher-severity alert takes precedence:
    CRITICAL > HIGH > MEDIUM > LOW.  The caller (signal engine) uses
    `should_escalate` to decide whether the new signal supersedes the existing
    alert or is absorbed into it.
    """
    strike_dec = Decimal(f"{float(strike):.2f}")
    level_rank = case(
        {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0},
        value=Alert.alert_level,
        else_=0,
    )
    q = (
        select(Alert)
        .where(
            and_(
                Alert.tenant_id == tenant_id,
                Alert.underlying_symbol == symbol.upper(),
                Alert.expiry == expiry,
                Alert.strike == strike_dec,
                Alert.option_type == option_type.upper(),
                Alert.status == "active",
                Alert.cooldown_expires_at > now,
            )
        )
        .order_by(level_rank.desc(), Alert.created_at.desc())
        .limit(1)
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def find_predecessor_alert(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    symbol: str,
    expiry: object,
    strike: Decimal | float,
    option_type: str,
    below_level: str,
    now: datetime,
) -> Optional[Alert]:
    """
    Find the most recent active alert for the same contract at a *lower* alert
    level.  Used to populate `escalated_from_alert_id` on newly escalated alerts
    so the UI can trace the escalation chain.

    Only searches within the last 24 hours to avoid linking stale alerts.
    """
    lower_levels = [
        lvl for lvl, rank in _LEVEL_ORDER.items()
        if rank < _LEVEL_ORDER.get(below_level, 0)
    ]
    if not lower_levels:
        return None

    expiry_value = expiry
    strike_dec = Decimal(f"{float(strike):.2f}")
    cutoff = now - timedelta(hours=24)

    q = (
        select(Alert)
        .where(
            and_(
                Alert.tenant_id == tenant_id,
                Alert.underlying_symbol == symbol.upper(),
                Alert.expiry == expiry_value,
                Alert.strike == strike_dec,
                Alert.option_type == option_type.upper(),
                Alert.alert_level.in_(lower_levels),
                Alert.status == "active",
                Alert.created_at >= cutoff,
            )
        )
        .order_by(Alert.created_at.desc())
        .limit(1)
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Escalation decision
# ---------------------------------------------------------------------------

def should_escalate(
    existing: Alert,
    new_level: str,
    new_priority_score: Optional[float],
) -> bool:
    """
    Decide whether a new signal should escalate past an existing active alert.

    Escalation is allowed when either condition holds:

    1. Level upgrade: the new alert_level is strictly higher than the existing
       one (e.g., MEDIUM → HIGH).  Level downgrades are always suppressed.

    2. Score improvement: both the existing and new priority_score are
       available, the levels are equal, and the new score is at least
       `_ESCALATION_SCORE_THRESHOLD` (20%) higher than the existing score.
       Prevents trivial re-fires from bypassing cooldown.
    """
    new_rank = _LEVEL_ORDER.get(new_level, 0)
    existing_rank = _LEVEL_ORDER.get(existing.alert_level, 0)

    # Level upgrade
    if new_rank > existing_rank:
        return True

    # Level downgrade → always suppress
    if new_rank < existing_rank:
        return False

    # Same level — allow only on meaningful score improvement
    if (
        new_priority_score is not None
        and existing.priority_score is not None
        and new_priority_score > existing.priority_score * (1.0 + _ESCALATION_SCORE_THRESHOLD)
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

def suppress_duplicate(
    existing: Alert,
    now: datetime,
    cooldown_minutes: int,
) -> None:
    """
    Update an existing active alert in-place to absorb a suppressed duplicate.

    - Increments `duplicate_count`.
    - Updates `last_seen_at` to `now`.
    - Extends `cooldown_expires_at` by `cooldown_minutes` from `now`, so a
      continuously hot contract does not escape suppression by inching forward
      in time.

    The caller is responsible for flushing/committing the session.
    """
    existing.duplicate_count = (existing.duplicate_count or 0) + 1
    existing.last_seen_at = now
    new_expiry = now + timedelta(minutes=cooldown_minutes)
    # Never shorten an already-longer cooldown window.
    if existing.cooldown_expires_at is None or new_expiry > existing.cooldown_expires_at:
        existing.cooldown_expires_at = new_expiry

    log.debug(
        "dedupe.suppressed",
        alert_id=str(existing.id),
        dedupe_key=existing.dedupe_key,
        duplicate_count=existing.duplicate_count,
        cooldown_expires_at=existing.cooldown_expires_at.isoformat() if existing.cooldown_expires_at else None,
    )


def mark_superseded(existing: Alert) -> None:
    """
    Mark an existing alert as superseded by an escalation.

    Sets status="superseded" and suppression_reason="escalated" so it is
    excluded from active-alert queries without being hard-deleted.

    The caller is responsible for flushing/committing the session.
    """
    existing.status = "superseded"
    existing.suppression_reason = "escalated"

    log.info(
        "dedupe.superseded",
        alert_id=str(existing.id),
        dedupe_key=existing.dedupe_key,
        alert_level=existing.alert_level,
    )
