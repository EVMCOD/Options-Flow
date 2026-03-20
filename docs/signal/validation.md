# Scanner Validation with Real Data

How to validate the options flow scanner against real IBKR delayed data,
interpret what you're seeing, and calibrate thresholds based on evidence.

---

## Workflow overview

```
1. Run the scanner (manually or via scheduler)
2. Check the run summary         → GET /api/v1/runs/{run_id}
3. Look at the filter breakdown  → signal_summary.filtered
4. Compare recent runs           → GET /api/v1/runs/compare?limit=5
5. Get threshold recommendations → GET /api/v1/diagnostics/threshold-review
6. Check specific alerts         → GET /api/v1/alerts/{alert_id}
7. Adjust one threshold at a time, repeat from step 1
```

---

## Step 1: Trigger a run

Manual trigger (API server must be running):
```http
POST /api/v1/jobs/trigger
```

Or from CLI (no server needed):
```bash
cd backend/
python -c "
import asyncio
from app.jobs.ingestion_job import run_ingestion_for_tenant
import uuid
asyncio.run(run_ingestion_for_tenant(uuid.UUID('00000000-0000-0000-0000-000000000001')))
"
```

---

## Step 2: Read the run summary

```http
GET /api/v1/runs/{run_id}
```

Or list recent:
```http
GET /api/v1/runs?limit=5&status=success
```

Key fields to check:

| Field | Healthy value | Warning if... |
|---|---|---|
| `status` | `"success"` | `"failed"` |
| `records_ingested` | > 0 during market hours | = 0 during market hours |
| `signal_summary.snapshots_above_min_volume` | > 50 for 2+ symbols | < 10 → bad feed or market closed |
| `signal_summary.passed_prefilters` | 30–80% of above-min-volume | < 10% → filters too aggressive |
| `signal_summary.features_created` | > 0 | = 0 → all filtered or no baseline |
| `signal_summary.alerts_created` | 0–5 per run is typical | > 20 → thresholds too low |
| `signal_summary.insufficient_baseline` | High early on, drops after 3+ runs | Always high → baseline never warming |

---

## Step 3: Interpret the filter breakdown

`signal_summary.filtered` tells you where contracts are being dropped. Each
value is the raw count for that filter in that run.

```json
"filtered": {
  "zero_price": 3,
  "far_expiry": 12,
  "deep_otm": 5,
  "low_premium": 8,
  "low_oi": 0
}
```

### What each filter means

| Filter | What it removes | Setting | Adjust when... |
|---|---|---|---|
| `zero_price` | Contracts with no usable bid/ask/last | hardcoded | Always expected; > 10 suggests feed problems |
| `far_expiry` | Contracts past MAX_DTE_DAYS | `MAX_DTE_DAYS` | If too high: include LEAPS flow. If too low: missing flow that does resolve |
| `deep_otm` | Contracts too far from ATM | `MAX_MONEYNESS_PCT` | If too high: your chain is wider than expected. Rarely fires with IBKR defaults |
| `low_premium` | Contracts with tiny notional | `MIN_PREMIUM_PROXY` | Most impactful tuning lever. Too high = missing real flow; too low = noise |
| `low_oi` | Contracts below min OI (default: disabled) | `MIN_OPEN_INTEREST` | Enable (50+) only when you have reliable OI from the feed |

### Filter rate heuristics

- **> 35% of contracts removed by a single filter** → probably too aggressive
- **< 2% removed** → the filter has minimal impact; could tighten it
- **zero_price > 10** → investigate the feed; delayed data may be degraded

---

## Step 4: Compare runs

```http
GET /api/v1/runs/compare?limit=5
```

Or with CLI:
```bash
cd backend/
python scripts/compare_runs.py --limit 5
python scripts/compare_runs.py --limit 10 --no-thresholds
```

The CLI shows a bar chart for each filter's removal rate, color-coded:
- **Green**: normal range (2–35%)
- **Red**: high removal (> 35%, potentially too aggressive)
- **Dim/grey**: very low removal (< 2%, minimal impact)

Look for:
- Consistent `low_premium` filtering 40%+ of contracts → raise `MIN_PREMIUM_PROXY` or lower it
- `far_expiry` filtering nothing → your IBKR chain is already within 60 DTE (expected with default settings)
- Alert count growing run over run → baseline warming up (good sign after first 3+ runs)
- Alert count spiking on one run → check if it's the same contracts every time (thin market noise)

---

## Step 5: Get threshold recommendations

```http
GET /api/v1/diagnostics/threshold-review?lookback_runs=10
```

Returns structured recommendations for each filter:
```json
{
  "filter_notes": [
    {
      "filter_name": "low_premium",
      "setting": "MIN_PREMIUM_PROXY",
      "current_value": 500.0,
      "avg_removal_rate": 0.41,
      "recommendation": "Removing 41% of evaluated contracts — may be too aggressive. Consider raising MIN_PREMIUM_PROXY to pass more contracts."
    }
  ],
  "alert_rate_note": "Alert rate is 8% of features — within expected range.",
  "baseline_note": "62% of processed contracts suppressed for insufficient baseline — normal for early runs."
}
```

This endpoint only analyzes runs from migration 005+. Earlier runs will show `runs_analyzed: 0`.

---

## Step 6: Inspect individual alerts

```http
GET /api/v1/alerts/{alert_id}
```

The enriched `AlertOut` response now includes:

| Field | Meaning |
|---|---|
| `anomaly_score` | Quality-adjusted score (this is what triggered the alert) |
| `raw_anomaly_score` | Score before quality penalties were applied |
| `quality_confidence` | Multiplier: 1.0 = no penalty, 0.85 = 15% penalty |
| `quality_flags` | JSON list: `["OI unavailable", "wide spread (85%)"]` |
| `dte_at_alert` | Days to expiry when the alert fired |
| `explanation` | Full human-readable summary with score breakdown |

**Red flags in an alert:**
- `quality_confidence < 0.85` — significant penalty; the signal is degraded
- `quality_flags = ["OI unavailable"]` AND `raw_anomaly_score < 4.0` — this alert is volume-only
- Same (symbol, expiry, strike, type) firing on every run — the baseline is too low for that contract; filter via `MIN_VOLUME` or wait for more baseline data

---

## Step 7: Deciding if a threshold is miscalibrated

### MIN_PREMIUM_PROXY is too high (e.g. $5000)
- `low_premium` filter removes > 50% of contracts
- Very few features and zero alerts despite market hours
- **Fix**: Lower to $500–$2000

### MIN_PREMIUM_PROXY is too low (e.g. $100)
- Many LOW/MEDIUM alerts on penny options with high volume
- `avg_anomaly_score` is inflated by high-volume cheap strikes
- **Fix**: Raise to $500–$1000

### MAX_DTE_DAYS is too permissive (e.g. 365)
- Far-dated LEAPS fill up features; they have wide spreads and low signal quality
- `quality_penalized` count is high (wide spreads common in LEAPS)
- **Fix**: Lower to 30–60 for near-term flow focus

### MAX_DTE_DAYS is too strict (e.g. 7)
- Most of the chain is filtered; only weekly options remain
- Features and alerts very sparse
- **Fix**: Raise to 30–60

### MIN_BASELINE_RUNS_FOR_ALERT is too high (e.g. 10)
- `insufficient_baseline` count stays very high even after many runs
- No alerts despite seeing volume spikes in features
- **Fix**: Lower to 3–5

### Alert score thresholds too low (causing noise)
- Many LOW alerts that don't correspond to visible market moves
- Alert rate > 20–30%
- **Fix**: The alert levels (≥1.5=LOW, ≥3=MEDIUM, ≥5=HIGH, ≥7=CRITICAL) are hardcoded but
  the quality penalty indirectly raises the effective bar. The main lever is `MIN_PREMIUM_PROXY`
  and `MIN_VOLUME` — they filter poor-quality contracts before scoring.

---

## Recommended initial universe for validation

Start with 2–3 symbols to build up baseline data quickly:

```http
POST /api/v1/universe
{"symbol": "SPY", "priority": 10}
{"symbol": "QQQ", "priority": 9}
```

Then expand once you've validated the signal is working:
```
AAPL, NVDA, TSLA, MSFT, AMD, META
```

**Why SPY and QQQ first:**
- Highest options volume → fastest baseline accumulation
- Most liquid → low `quality_penalized` rate, good bid/ask
- Wide, well-known chains → easier to cross-reference with other data sources
- Index ETFs → not affected by earnings surprises that distort individual stock signals

---

## Log events to watch during real runs

```
ibkr.session_ready         → Connected to TWS; delayed data confirmed
ibkr.chain_complete        → Shows returned vs skipped per symbol
signal.started             → Signal engine beginning; run_id logged
signal.filtered_*          → One of the 5 pre-filters removed a contract (DEBUG)
signal.skipped_alert_insufficient_baseline → Feature stored, alert suppressed (INFO)
signal.finished            → Full breakdown: features, alerts, filter counts, elapsed_ms
ingestion_job.signals_complete → Final job log with all signal metrics
```

Use structlog's JSON output to grep these in production:
```bash
journalctl -u ofr-backend | jq 'select(.event == "signal.finished")'
```

---

## Calibration cycle

The recommended calibration loop during development:

1. Run scanner 3–5 times to warm up baseline
2. Read `GET /runs/compare?limit=5` — check trends
3. Read `GET /diagnostics/threshold-review` — check recommendations
4. Change **one** threshold (document what you changed and why)
5. Run scanner 2–3 more times
6. Compare again — did the target metric improve?
7. If yes: lock in the change. If no: revert and try something else.

Do not change multiple thresholds simultaneously — you lose the ability to
attribute observed changes to a specific adjustment.
