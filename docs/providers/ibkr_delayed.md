# IBKR Delayed Options Data Provider

**Provider type:** `ibkr_delayed`
**Status:** Bridge / development — usable with caveats (see Limitations)
**Data freshness:** 15–20 minute delayed snapshots
**Cost:** Free for any IBKR account (no market data subscription required)

---

## What it does

Connects to Interactive Brokers TWS or IB Gateway via the `ib_insync` Python
library and pulls a delayed options snapshot for each symbol in the tenant's
universe. The connection is read-only — no orders, no account mutations.

The provider filters the chain to a manageable subset:

```
nearest max_expiries expiry dates × ATM ± strike_count strikes × C + P
```

For SPY with defaults (max_expiries=4, strike_count=10):
~168 contracts per scan cycle. Well within IBKR's API limits.

---

## Prerequisites

### 1. Install ib_insync

`ib_insync` is **not** included in `requirements.txt` (it's optional and
brings in IBKR's native API code). Install it separately in the backend env:

```bash
pip install "ib_insync>=0.9.86"
```

### 2. Run TWS or IB Gateway

The provider connects to a running TWS (Trader Workstation) or IB Gateway
instance. IB Gateway is the lighter choice — no GUI, lower memory footprint.

**Paper account ports (typical defaults):**
| Application  | Port |
|---|---|
| IB Gateway paper | 4002 |
| IB Gateway live  | 4001 |
| TWS paper        | 7497 |
| TWS live         | 7496 |

### 3. Enable API access

In TWS: **Edit → Global Configuration → API → Settings**

In IB Gateway: **Configure → Settings → API → Settings**

Required:
- ✅ Enable ActiveX and Socket Clients
- ✅ Socket port matches your `credentials_json.port`
- Add `127.0.0.1` to trusted IPs (or allow all)
- Client ID must be unique per simultaneous connection

---

## Activating for a tenant

```http
POST /api/v1/tenants/{tenant_id}/providers
Content-Type: application/json

{
  "provider_type": "ibkr_delayed",
  "credentials_json": {
    "host":      "127.0.0.1",
    "port":      4002,
    "client_id": 10
  },
  "config_json": {
    "use_delayed_data": true,
    "timeout_seconds":  30,
    "max_expiries":     4,
    "strike_count":     10,
    "exchange":         "SMART",
    "batch_size":       50
  }
}
```

Then set it as the default:

```http
POST /api/v1/tenants/{tenant_id}/providers/{config_id}/set-default
```

The next scheduled scan (or a manual trigger) will use IBKR delayed data.

---

## Configuration reference

### `credentials_json` (required)

| Field | Type | Description |
|---|---|---|
| `host` | string | TWS/IB Gateway host. Use `"127.0.0.1"` for local. |
| `port` | int | API socket port (see table above). |
| `client_id` | int | Unique identifier for this connection. Must not clash with other active sessions. |

### `config_json` (all optional, shown with defaults)

| Field | Type | Default | Description |
|---|---|---|---|
| `use_delayed_data` | bool | `true` | `true` = 15-min delayed (free). `false` = live (requires subscription). |
| `timeout_seconds` | float | `30` | Per-operation timeout. Increase on slow networks. |
| `max_expiries` | int | `4` | Number of nearest expiry dates to include. |
| `strike_count` | int | `10` | ATM ± N strikes. Total strikes = 2N+1 per expiry. |
| `exchange` | string | `"SMART"` | IBKR routing. SMART works for most US equities and ETFs. |
| `batch_size` | int | `50` | Contracts per market data batch. Max ~100 for most accounts. |

---

## Data contract

Fields returned in each `OptionContract`:

| Field | Source | Notes |
|---|---|---|
| `underlying_symbol` | Contract metadata | |
| `expiry` | `lastTradeDateOrContractMonth` parsed | |
| `strike` | `contract.strike` | |
| `option_type` | `contract.right` | `"C"` or `"P"` |
| `spot_price` | Stock ticker (`last` → `close` → bid-ask mid) | |
| `bid` | `ticker.bid` | Estimated if unavailable |
| `ask` | `ticker.ask` | Estimated if unavailable |
| `last` | `ticker.last` → `ticker.close` → bid-ask mid | |
| `volume` | `ticker.volume` (day volume, cast to int) | 0 if not populated |
| `open_interest` | `ticker.openInterest` (prior-close OI) | 0 if not populated by delayed feed |
| `implied_vol` | `ticker.modelGreeks.impliedVol` | `null` if IBKR model hasn't computed it |
| `as_of_ts` | `datetime.now(UTC)` at fetch time | Approximate — delayed data is 15–20 min old |
| `source` | `"ibkr_delayed"` | |

---

## Known limitations

### Delayed data is stale by design
At 15–20 minutes of delay, a volume spike detected by this provider may reflect
activity that happened well before the current scan. This is acceptable for
development and bridge use but not for a time-sensitive production signal.

### Volume is cumulative, not per-interval
`volume` is the contract's day volume from market open. The signal engine
computes `volume_ratio` against a historical baseline, so this still works
but the per-interval resolution is lower than with a real-time feed.

### Open interest may be 0
IBKR delayed snapshots don't always populate open_interest. The signal engine
treats `open_interest=0` by skipping the `volume_oi_ratio` component of the
anomaly score (it's weighted at 20%) — results are still valid.

### Implied vol may be null
`modelGreeks.impliedVol` requires IBKR's model to have run on the contract.
For very OTM or short-DTE contracts it may not be populated. The signal engine
handles `implied_vol=None` correctly.

### Market hours only (approximately)
Outside regular market hours (9:30–16:00 ET), delayed data is typically
unavailable and the provider returns an empty list (not an error). The
signal engine skips runs with no snapshots gracefully.

### SPX, VIX, and index options
Index options (SPX, XSP, VIX) use non-standard symbology and may require
a different `exchange` (e.g., `"CBOE"` for VIX). This is not tested.
Stick to equity ETFs (SPY, QQQ, IWM) and individual stocks for now.

### Client ID conflicts
If two tenants share the same `client_id` and both try to connect simultaneously,
the second connection will be rejected. Use distinct `client_id` values per
tenant (e.g., 10 for tenant A, 11 for tenant B).

### TWS session timeouts
IB Gateway / TWS auto-disconnects API clients after periods of inactivity
(configurable, default varies). If the provider returns `IBKRConnectionError`,
check that the TWS session is still live.

---

## Validating runs with the diagnostic tools

These are the concrete steps to validate IBKR delayed data with the built-in
diagnostic endpoints and CLI. Do this before trusting any alerts.

### Option A: CLI script (no API server needed)

```bash
cd backend/

# Test the default tenant's provider using its first 2 universe symbols
python scripts/validate_provider.py \
  --tenant-id 00000000-0000-0000-0000-000000000001

# Test specific symbols
python scripts/validate_provider.py \
  --tenant-id <UUID> --symbols SPY,QQQ

# Test a specific provider config by ID
python scripts/validate_provider.py \
  --config-id <config-UUID> --symbols SPY --max-symbols 1

# Suppress sample contract table (faster output)
python scripts/validate_provider.py \
  --tenant-id <UUID> --symbols SPY --no-samples
```

The script prints a color-coded terminal report with verdict, quality metrics,
per-symbol breakdown, and sample contracts. Exit code 0 = usable/good, 1 = poor/limited/error.

### Option B: API endpoints (API server must be running)

**Check effective (non-secret) config:**
```http
GET /api/v1/diagnostics/provider/{config_id}
```

**Run a test fetch:**
```http
POST /api/v1/diagnostics/provider/{config_id}/test-fetch?symbols=SPY,QQQ&max_symbols=2
```

Response includes quality verdict, null field rates, and sample contracts.
⚠️ This is synchronous. For IBKR, budget 30–60 s per symbol.

**Check provider health:**
```http
GET /api/v1/tenants/{tenant_id}/providers/health
```

### Interpreting the quality verdict

| Verdict | Meaning | What to do |
|---|---|---|
| `good` | >95% usable bid/ask, broad chain | Ready for production use |
| `usable` | 80–95% usable bid/ask | Acceptable for signal generation |
| `limited` | 50–80% usable bid/ask or low contract count | Usable for dev/validation, weaker signals |
| `poor` | <50% usable bid/ask, or all symbols empty | Investigate before trusting signals |

### Signal interpretation by situation

**All symbols returned empty:**
→ Market is closed (before 09:30 or after 16:00 ET). Normal. Run again during market hours.

**Symbols empty during market hours:**
→ Delayed data feed is degraded. Check `ibkr.no_spot_price` in logs. Verify TWS/IB Gateway is connected to IBKR servers.

**Low OI coverage (< 20%):**
→ Expected with delayed feed. The OI component of the anomaly score (20% weight) will be zero for most contracts. Signals are volume-ratio based only. This is acceptable.

**Low IV coverage (< 50%):**
→ Normal for far OTM and short-DTE strikes. IV component isn't used in scoring — it's informational only.

**Connection error in `error_detail`:**
→ TWS/IB Gateway not reachable. Check: (1) IB Gateway is running, (2) API port matches config, (3) API access is enabled in TWS settings.

---

## Inspecting ingestion runs

These are the concrete things to check when you first activate this provider
for a tenant and want to know if it's working correctly.

### Step 1: List recent runs

```http
GET /api/v1/runs?tenant_id={id}&limit=5
GET /api/v1/runs?tenant_id={id}&status=failed   ← find failures quickly
```

A healthy run looks like:

| Field | Expected value |
|---|---|
| `status` | `"success"` |
| `market_data_mode` | `"delayed"` |
| `provider_type` | `"ibkr_delayed"` |
| `records_ingested` | > 0 (typically 100–500 depending on universe and chain width) |
| `error_message` | `null` |

A run that returned 0 records during market hours is a warning sign. Look at `error_message` — it will say `"0 records from N symbol(s). Provider returned no contracts..."` instead of being null. This distinguishes "market closed" from "something is broken".

A run that returned 0 records outside market hours (before 9:30 ET or after 16:00 ET) is expected and normal.

**Get enriched detail for a specific run (with derived counts):**
```http
GET /api/v1/runs/{run_id}
```
Returns `features_count`, `alerts_count`, and `distinct_symbols` in addition to all run metadata — no need to join tables manually.

### Step 2: Check the provider health endpoint

```http
GET /api/v1/tenants/{id}/providers/health
```

After a successful run:
- `status` should be `"healthy"` (updated by `mark_provider_healthy`)
- `last_healthy_at` should be recent

If `status` is `"error"`, `last_error` will contain the exception message. Common errors:
- `"Connection refused"` → TWS/IB Gateway not running
- `"Timed out connecting"` → port mismatch or firewall
- `"Required credential 'host' is missing"` → misconfigured `credentials_json`

### Step 3: Check the logs

Key log events to look for when debugging a real run:

| Event | Meaning |
|---|---|
| `ibkr.session_ready` | Connected to TWS; shows host, port, data_type |
| `ibkr.fetching_chain` | Shows expiries, strikes, total_contracts before qualification |
| `ibkr.chain_complete` | Shows returned vs skipped_no_data per symbol |
| `ibkr.fetch_complete` | Per-symbol elapsed time and final contract count |
| `ibkr.no_spot_price` | Market closed or no delayed feed for this symbol |
| `ingestion.symbol_done` | Per-symbol: fetched, stored, quality_skipped, elapsed |
| `ingestion.finished` | Full run: records, symbols_attempted, market_data_mode |
| `signal.skipped_alert_insufficient_baseline` | Alert suppressed — not enough historical runs yet |
| `signal.skipped_zero_price` | Snapshot dropped — no usable price data |

### Step 4: Understand the baseline warm-up period

The signal engine requires `MIN_BASELINE_RUNS_FOR_ALERT = 3` successful historical runs before generating alerts for a given contract. This means:

- **First 3 runs**: Features are computed and stored, but no alerts are raised. This is intentional — the baseline is a fallback estimate, not a real measured value.
- **After 3+ runs**: Alerts are generated normally based on measured historical volumes.

This prevents the first-run spam that would otherwise occur with IBKR delayed data (where `open_interest` may be 0 and volume baselines are fabricated).

To check how many historical runs exist:
```http
GET /api/v1/runs?tenant_id={id}&status=success
```

### Step 5: Metrics to review before trusting alerts

Before treating alerts from this provider as actionable:

1. **records_ingested > 0** on the last 3+ runs — confirms delayed data is flowing
2. **provider.status = "healthy"** — confirms no connection errors
3. **signal features exist** — check `GET /api/v1/signals` for the run
4. **anomaly_score distribution** — first alerts after warm-up should be concentrated on genuinely unusual volume, not every contract
5. **OI = 0 alerts** — if most alerts have `volume_oi_ratio = null` (OI was 0), the OI component of the score isn't contributing; alerts are pure volume-based. This is valid but less precise.

### Red flags to investigate

- All symbols returning 0 contracts during market hours → check IBKR connection and delayed data type
- `quality_skipped` > 20% of fetched contracts → delayed feed may be degraded for those symbols
- Alerts fire on every run for the same contracts → may be thin/illiquid contracts with artificially low baselines; consider raising `MIN_VOLUME` in config

---

## Upgrading this provider

This is intentionally a **bridge implementation**. Clear upgrade paths:

1. **Real-time data**: Switch to `reqMktData` streaming + a persistent IB
   session (singleton per-process, reconnect on disconnect). Eliminates the
   per-fetch connect/disconnect overhead and gives tick-level resolution.

2. **Historical OI**: Use `reqHistoricalData` with `whatToShow="OPTION_VOLUME"`
   to backfill accurate historical OI for baseline computation.

3. **Greeks**: Request `reqMktData` with `genericTickList="100,101,106"` to
   get delta, gamma, theta, vega alongside IV.

4. **SPX/index support**: Add special-case handling for index symbology (no
   stock qualifier, exchange="CBOE" for VIX, etc.).

5. **Production deployment**: Move from a local TWS setup to IB Gateway
   running in a Docker container or a dedicated VPS co-located with your stack.
