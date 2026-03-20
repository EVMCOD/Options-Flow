# Alert Policy — Options Flow Radar

## Why this document exists

The system was generating thousands of alerts per run (observed: ~7,879 active, ~3,266 CRITICAL).
That is not a signal — it is noise.  A trader cannot act on 3,000 CRITICAL alerts; they will
ignore all of them.  This document describes the corrected policy, the reasoning behind each
threshold, and how to tune further if needed.

---

## What changed and why

### 1. Severity thresholds raised significantly

The anomaly score runs 0–10.  Previously:

| Level    | Old threshold | New threshold | Why it changed |
|----------|---------------|---------------|----------------|
| LOW      | 1.5           | **3.0**       | 1.5 fired on any 2× spike at z=2 — that is statistical noise |
| MEDIUM   | 3.0           | **5.0**       | 3.0 was reachable with ordinary intraday volume patterns |
| HIGH     | 5.0           | **7.0**       | Needs very significant, sustained flow deviation |
| CRITICAL | 7.0           | **8.5**       | Must be exceptional — 10× baseline AND z≥4.5 simultaneously |

**Score reference** (raw, without quality penalty):

```
5× spike + z=3.0  →  (0.40×0.5 + 0.40×0.6) × 10  ≈  4.4   →  LOW (just)
8× spike + z=4.0  →  (0.40×0.8 + 0.40×0.8) × 10  ≈  6.4   →  MEDIUM
10× spike + z=5.0 →  max                           =  8.0   →  HIGH (needs VOI too for CRITICAL)
```

CRITICAL now requires both the volume ratio AND z-score components to be near their maximums,
*plus* the VOI (volume/OI ratio) component to contribute.  A single outlier dimension is not enough.

### 2. Priority score gates for HIGH and CRITICAL

Even if anomaly score qualifies a contract for HIGH or CRITICAL, it must also pass a minimum
**priority score** — a composite of anomaly strength + notional value + data quality:

| Level    | Required priority_score |
|----------|------------------------|
| HIGH     | ≥ 4.0                  |
| CRITICAL | ≥ 5.0                  |

This blocks:
- High-anomaly contracts with tiny notional (penny options, 10-contract trades)
- High-anomaly contracts with degraded data quality (no OI, wide spreads)

LOW and MEDIUM have no priority gate — they are already screened by the score thresholds.

### 3. Contract-level deduplication

Previously, dedupe keys included the alert level.  This meant a contract could accumulate
simultaneous LOW + MEDIUM + HIGH alerts as its anomaly score drifted between runs.

The new behavior: **one active alert per contract per cooldown window**, regardless of level.
When a new signal arrives for a contract that already has an active alert:

- **New level > existing level** → escalation: old alert marked superseded, new alert created
- **New level ≤ existing level** → absorbed: `duplicate_count` on existing alert incremented, cooldown extended
- This includes the case where a MEDIUM contract drifts to LOW — the LOW is absorbed, not filed as a separate alert

### 4. Cooldown window extended: 60 min → 240 min (4 hours)

A 60-minute cooldown means the same hot contract re-alerts every hour through a session.
240 minutes (4 hours) covers an entire trading session half.  If a contract genuinely
re-activates after cooling, it will create a fresh alert with full context.

### 5. Pre-filter tightening

| Setting                  | Old   | New        | Effect |
|--------------------------|-------|------------|--------|
| `MIN_PREMIUM_PROXY`      | $500  | **$2,000** | Filters penny options and micro-lot trades |
| `MIN_BASELINE_RUNS_FOR_ALERT` | 3 | **10**   | 50 min of history before alerting (was 15 min) |
| `MAX_MONEYNESS_PCT`      | 20%   | **15%**    | Stays closer to ATM; deep OTM signals are unreliable |

---

## What each level means now

### LOW
- Anomaly score ≥ 3.0
- Notional ≥ $2,000
- Genuine above-baseline volume burst, but not yet confirmed by multiple dimensions
- **Use:** background monitoring, watchlist seeding.  Not actionable alone.

### MEDIUM
- Anomaly score ≥ 5.0
- Consistent multi-dimensional signal: volume ratio AND z-score both elevated
- **Use:** worth watching.  Look for corroborating price action or news.

### HIGH
- Anomaly score ≥ 7.0 AND priority_score ≥ 4.0
- Very significant flow with decent notional.  Rare in a normal session.
- **Use:** actionable.  Review contributing factors, check flow story for the symbol.

### CRITICAL
- Anomaly score ≥ 8.5 AND priority_score ≥ 5.0
- Exceptional.  Should appear a handful of times per week at most.
- A CRITICAL alert means: 8–10× baseline volume, z-score in the top percentile,
  meaningful notional, and acceptable data quality.  All four dimensions must align.
- **Use:** immediate attention.

---

## Overview metrics — what the numbers mean now

| Metric | Meaning |
|--------|---------|
| **Active H/C** | Active HIGH + CRITICAL alerts right now.  This is the operational signal count. |
| **Critical / High** | Active HIGH + CRITICAL count, broken down.  Active alerts only — not all-time. |
| **Alert Distribution** | Active alerts by severity (active only, not historical). |
| **Total Alerts** | All-time alert count.  Grows monotonically.  Historical reference only. |
| **Top Symbols** | Symbols with active HIGH/CRITICAL alerts in the last 24 h. |

---

## How to tune per symbol

Every threshold in `config.py` can be overridden per symbol via `TenantSymbolSettings`.

Useful overrides for common symbols:

| Symbol | Suggested min_premium_proxy | Suggested min_alert_level | Notes |
|--------|-----------------------------|--------------------------|-------|
| SPY    | $5,000+                     | MEDIUM                   | Very liquid; low threshold = noise |
| QQQ    | $3,000+                     | MEDIUM                   | Similar to SPY |
| AAPL   | $2,000                      | LOW                      | Standard |
| NVDA   | $2,000                      | LOW                      | Standard; high IV creates more anomalies |
| TSLA   | $2,000                      | LOW                      | High volatility; accept more signals |
| META   | $2,000                      | LOW                      | Standard |
| MSFT   | $3,000                      | MEDIUM                   | Lower option activity; raise bar |
| AMD    | $1,500                      | LOW                      | Smaller cap; lower notional threshold |

To apply a per-symbol override, use the settings API or directly insert into `tenant_symbol_settings`.

---

## How to validate the policy is working

After the next ingestion run:

```bash
# Check alert level distribution
curl -s http://localhost:8000/api/v1/metrics/summary | \
  jq '.data | {active_h_c: .active_alerts, by_level: .alerts_by_level}'

# Should see dramatically fewer CRITICAL/HIGH
# Target: CRITICAL < 10, HIGH < 50 per session

# Check suppressed vs created ratio
curl -s http://localhost:8000/api/v1/ingestion-runs?limit=1 | \
  jq '.data[0].signal_summary | {created: .alerts_created, suppressed: .alerts_suppressed, escalated: .alerts_escalated}'

# A healthy ratio: suppressed >> created (most repetitions absorbed)
```

---

## Global defaults (`config.py`)

```
ALERT_LEVEL_LOW      = 3.0    # (was 1.5)
ALERT_LEVEL_MEDIUM   = 5.0    # (was 3.0)
ALERT_LEVEL_HIGH     = 7.0    # (was 5.0)
ALERT_LEVEL_CRITICAL = 8.5    # (was 7.0)

MIN_PRIORITY_SCORE_HIGH     = 4.0  # new gate
MIN_PRIORITY_SCORE_CRITICAL = 5.0  # new gate

MIN_PREMIUM_PROXY           = 2000.0  # (was 500)
MIN_BASELINE_RUNS_FOR_ALERT = 10      # (was 3)
MAX_MONEYNESS_PCT            = 0.15   # (was 0.20)
ALERT_COOLDOWN_MINUTES       = 240    # (was 60)
```

All values are overridable via `.env` or per-tenant/per-symbol settings.
