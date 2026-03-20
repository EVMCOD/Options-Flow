# Signal Engine Calibration

**Updated for:** IBKR delayed options data (bridge provider)
**Applies to:** `backend/app/services/signal.py` + `backend/app/core/config.py`

---

## Anomaly score formula

Score is on a **0–10 scale**, quality-adjusted.

```
raw   = (0.40 × norm_ratio + 0.40 × norm_z + 0.20 × norm_voi) × 10
score = raw × quality_confidence
```

| Component | Weight | Normalization | Saturates at |
|---|---|---|---|
| `volume_ratio` | 0.40 | ratio / 10 → [0, 1] | 10× baseline = 4.0 pts |
| `\|z-score\|` | 0.40 | z / 5 → [0, 1] | z=5 = 4.0 pts |
| `volume/OI ratio` | 0.20 | VOI / 0.5 → [0, 1] | VOI≥0.5 = 2.0 pts |

The VOI component is 0 when `open_interest == 0` (common with IBKR delayed).
The max achievable score without OI is **8.0** (0.40+0.40 × 10).

### Alert levels

| Score | Level |
|---|---|
| ≥ 7.0 | CRITICAL |
| ≥ 5.0 | HIGH |
| ≥ 3.0 | MEDIUM |
| ≥ 1.5 | LOW |

---

## Quality confidence penalty

After the raw score is computed, a multiplicative penalty is applied for
degraded data. The floor is **0.50** — a contract with all penalties applied
still gets at least half its raw score.

| Condition | Penalty | Setting |
|---|---|---|
| `open_interest == 0` | −10% | `SCORE_OI_MISSING_PENALTY = 0.10` |
| Bid/ask spread > `MAX_BID_ASK_SPREAD_PCT` (when mid ≥ $0.05) | −5% | `SCORE_SPREAD_WIDE_PENALTY = 0.05` |

**Example:** A raw score of 7.5 with missing OI and a wide spread becomes
`7.5 × (1.0 − 0.10 − 0.05) = 7.5 × 0.85 = 6.375` — still HIGH but not CRITICAL.

The quality flags and penalty are surfaced in the alert `explanation` field.

---

## Pre-filters

These filters run **before** the expensive baseline DB query, discarding contracts
that are structurally uninteresting or have unreliable data.

| Filter | Default | Setting | Rationale |
|---|---|---|---|
| Zero price | `mid < $0.02 and last < $0.02` | hardcoded | No usable price → volume signal is meaningless |
| DTE | `> 60 days` | `MAX_DTE_DAYS = 60` | Far-dated contracts have wide spreads and low near-term sensitivity |
| Moneyness | `\|spot/strike − 1\| > 20%` | `MAX_MONEYNESS_PCT = 0.20` | Deep OTM/ITM markets are thin; signals unreliable |
| Premium proxy | `< $500` | `MIN_PREMIUM_PROXY = 500.0` | Tiny notional contracts are noise (e.g. 100 contracts × $0.03 = $300) |
| Min OI | `< 0` (disabled) | `MIN_OPEN_INTEREST = 0` | Off by default for IBKR delayed where OI is often 0 |

Filter counts are emitted in the `signal.finished` structured log event:
`filtered_zero_price`, `filtered_far_expiry`, `filtered_deep_otm`, `filtered_low_premium`, `filtered_low_oi`.

---

## Baseline computation

For each (symbol, expiry, strike, option_type) combination, the signal engine
queries the last `BASELINE_LOOKBACK_RUNS = 20` successful ingestion runs
to get historical volumes, then computes mean and std.

**Fallback** when fewer than 3 historical volumes exist:
```
baseline_volume = max(50, open_interest × 0.02)
baseline_std    = baseline_volume × 0.5
```
With OI=0, this gives `baseline_volume = 50` — a very low floor.
A contract with volume=100 would show a 2× ratio, which could score ~3.2
even on the first run. This is why the baseline sufficiency guard exists.

### Baseline sufficiency guard

No alerts are generated until `MIN_BASELINE_RUNS_FOR_ALERT = 3` real
data points exist for the contract. Features are still stored (for observation)
but suppressed from alerting. This is logged as `signal.skipped_alert_insufficient_baseline`.

**Why 3 and not more?** Three samples give the first usable mean and std.
With a 5-minute scan interval, 3 runs accumulate in 15 minutes of market hours.
This is aggressive — raise to 5–10 for less noise if you run more frequent scans.

---

## Recommended starting universe

| Symbol | Why include |
|---|---|
| SPY | Highest options volume on any US exchange; most liquid; best baseline |
| QQQ | Second highest; strong institutional flow |
| AAPL | Deep chain; common vehicle for single-stock event flow |
| NVDA | High IV, frequent sector rotation signals |
| TSLA | Volatile, retail + institutional mixed flow |
| MSFT | Large cap, often moves with AAPL/QQQ; good corroboration |
| AMD | Semiconductor proxy; corroborates NVDA signals |
| META | High IV around earnings; good for testing alert quality |

Configured as `SCANNER_UNIVERSE` in `config.py`. For IBKR delayed with
`max_expiries=4` and `strike_count=10`, each symbol produces ~168 contracts
per scan cycle. The full 8-symbol universe yields ~1,344 contracts per run.

---

## Tuning recommendations by situation

### Too many LOW/MEDIUM alerts
- Raise `MIN_VOLUME` (e.g. 100 → 250): requires more trading activity
- Raise `MIN_PREMIUM_PROXY` (e.g. 500 → 2000): requires meaningful notional
- Raise `MIN_BASELINE_RUNS_FOR_ALERT` (3 → 5): requires more history
- Raise `SCORE_OI_MISSING_PENALTY` (0.10 → 0.20): heavier discount without OI

### Too few HIGH/CRITICAL alerts (after warm-up)
- Lower `MIN_VOLUME` (100 → 50) — if universe has low-volume symbols
- Lower `MAX_DTE_DAYS` (60 → 30) — focus on near-term only
- Lower `MAX_MONEYNESS_PCT` (0.20 → 0.10) — focus tightly on ATM

### Spikes on the same contracts every run (persistent alerts)
- These are likely thin/illiquid contracts with low baselines
- Check `volume_ratio` — if it's always 2–3× on the same contract, the
  baseline is too low (not enough historical data, or volume is genuinely
  always elevated at that strike)
- Raise `MIN_BASELINE_RUNS_FOR_ALERT` to let baseline mature
- Check `quality_skipped` count in ingestion runs — may indicate a bad
  feed period inflating baselines

### IBKR delayed vs live: expected differences
| Metric | IBKR delayed | Live feed |
|---|---|---|
| `open_interest` | Often 0 | Populated |
| `volume` | Cumulative day vol | Cumulative or per-interval |
| Score accuracy | 80% (VOI component inactive) | 100% |
| Recommended `MIN_BASELINE_RUNS_FOR_ALERT` | 3–5 | 10–20 |
| Recommended `MIN_PREMIUM_PROXY` | 500 | 2000+ |

---

## Alert explanation format

Each alert's `explanation` field includes:

```
{LEVEL} anomaly: {SYMBOL} {EXPIRY} {DTE}DTE ${STRIKE} {MONEYNESS} {type}.
Volume {VOL} vs baseline {BASE} (ratio {R}×, z {Z}, VOI {V}) (~${PREMIUM} premium proxy).
IV {IV}%.
Score {SCORE}/10 [raw {RAW}, −{PENALTY}% quality penalty].
Quality notes: {FLAGS}.
```

Example:
```
HIGH anomaly: SPY 2024-04-19 12DTE $550 ATM call.
Volume 3,450 vs baseline 820 (ratio 4.2×, z +3.1, VOI 18.20%) (~$94,875 premium proxy).
IV 24.5%.
Score 5.51/10 [raw 6.13, −10% quality penalty].
Quality notes: OI unavailable.
```
