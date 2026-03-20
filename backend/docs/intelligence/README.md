# Intelligence Layer — v1

First iteration of product-differentiating capabilities built on top of the calibrated signal engine.

---

## Architecture

```
backend/app/intelligence/
├── ranking.py      — Smart Flow Ranking (Capacity 1 + 4)
├── patterns.py     — Pattern Detection (Capacity 2)
├── flow_story.py   — Intraday Flow Story (Capacity 5)
└── schemas.py      — Pydantic output types for all endpoints

backend/app/routers/intelligence.py — API endpoints

Database (migration 007):
  alerts.priority_score            FLOAT nullable
  alerts.contributing_factors_json JSON nullable
  tenant_symbol_settings.priority_weight FLOAT nullable
  tenant_symbol_settings.watchlist_tier  VARCHAR(20) nullable
```

---

## Capacity 1 — Smart Flow Ranking

**What it does:** ranks alerts by a composite priority score that combines signal strength, economic relevance, data quality, and per-client symbol preference.

**Formula:**
```
base_score = (
    0.45 × (anomaly_score / 10)          # statistical signal strength
  + 0.30 × clamp(premium_proxy / 50k, 0, 1)  # economic relevance (saturates at $50k)
  + 0.25 × quality_confidence            # data quality (0.5–1.0)
) × priority_weight × 10                 # per-client symbol multiplier (default 1.0)

ranked_score = base_score × exp(-0.05 × hours_since_creation)
# half-life ≈ 14 hours
```

`base_score` is stored on the alert at creation time (stable, historical).
`ranked_score` is computed live at query time (decays with age).

**API:**
```
GET /api/v1/intelligence/alerts-ranked?hours=24&limit=50&symbol=SPY
```

**When to use:** replace the default `alerts` endpoint with this when you want the most actionable alerts first, not just the most recent.

---

## Capacity 2 — Pattern Detection

**What it does:** detects recurring structure across alerts that is more meaningful than isolated prints.

**Patterns detected:**

| Pattern | Description | Trigger |
|---------|-------------|---------|
| `repeated_prints` | Same (symbol, expiry, strike, type) ≥ N times | Persistent directional interest |
| `strike_cluster` | Multiple alerts near the same strike (±5%) | Price-level accumulation |
| `expiry_cluster` | Multiple alerts same expiry across strikes | Event-driven flow |
| `volume_acceleration` | Anomaly scores escalating across sequential prints | Intensifying interest |

**Not implemented (and why):**
- Sweep detection: requires tick-level data. Delayed snapshots capture aggregated volume. A heuristic here would produce too many false positives.

**Output `strength` (0–1):** count-based heuristic. 1.0 = very strong. Not a calibrated probability.

**API:**
```
GET /api/v1/intelligence/patterns?hours=6&symbol=SPY&min_occurrences=3
```

**Limitations:** computed on demand from the last N hours of alerts. No persistence or push notifications in v1.

---

## Capacity 3 — Per-Client / Per-Symbol Intelligence

**What it does:** makes the ranking score respond to client-specific symbol preferences.

**Fields added to `tenant_symbol_settings`:**

| Field | Type | Range | Effect |
|-------|------|-------|--------|
| `priority_weight` | float nullable | 0.0–3.0 | Multiplied into `base_score`. 0 = suppressed; 1 = neutral; 2+ = featured. |
| `watchlist_tier` | string nullable | "core" / "secondary" / null | Client-facing label. Shown in Signal Settings UI. |

**Configuration:** Signal Settings → Symbol Overrides → Intelligence/Ranking section.

**Effect on product:** a symbol with `priority_weight = 2.0` will rank 2× higher in the ranked alerts list vs the same signal on an un-configured symbol. `priority_weight = 0` means the symbol's alerts appear last (or can be filtered out).

---

## Capacity 4 — Actionable Alert Explanations

**What it does:** enriches each alert with structured contributing factors and a more informative explanation.

**`contributing_factors_json` schema:**
```json
{
  "volume_spike": {
    "ratio": 8.2,
    "baseline_avg": 150,
    "current": 1230,
    "zscore": 4.1,
    "assessment": "extreme"   // "elevated" | "high" | "very_high" | "extreme"
  },
  "notional": {
    "premium_proxy_usd": 45000,
    "assessment": "large"     // "small" | "moderate" | "large" | "institutional"
  },
  "timing": {
    "dte": 5,
    "assessment": "near_term" // "near_term" | "short_term" | "medium_term" | "long_term"
  },
  "quality": {
    "confidence": 0.90,
    "flags": ["wide spread (85%)"],
    "data_source": "ibkr_delayed",
    "assessment": "clean"     // "clean" | "minor_flags" | "reduced"
  },
  "moneyness": {
    "spot": 545.2,
    "strike": 545.0,
    "distance_pct": 0.0004,
    "label": "ATM"            // "ITM" | "ATM" | "OTM"
  },
  "iv": { "value": 0.25 }    // null if IV not available
}
```

**Assessment thresholds:**

| Metric | Thresholds |
|--------|-----------|
| volume spike | < 3× = elevated · < 5× = high · < 10× = very_high · ≥ 10× = extreme |
| notional | < $5k = small · < $20k = moderate · < $100k = large · ≥ $500k = institutional |
| DTE | ≤ 5 = near_term · ≤ 14 = short_term · ≤ 30 = medium_term · else = long_term |
| quality | conf ≥ 0.95 = clean · ≥ 0.80 = minor_flags · else = reduced |

**Explanation format:**
```
[HIGH] SPY $545C · exp 2025-02-07 (5DTE) · ATM
Vol spike: 1,230 vs baseline 150 — 8.2× (z +4.1). Extreme.
Premium proxy: ~$45,200. Large.
IV: 25.0%.
Score: 7.2/10 [raw 7.8, −8% quality]. Data: ibkr_delayed · wide spread (85%).
```

---

## Capacity 5 — Intraday Flow Story

**What it does:** generates a per-symbol session summary on demand.

**Output fields:**
- `total_alerts`, `alert_distribution` — activity volume and severity
- `call_put_balance` — directional lean
- `total_notional` — estimated USD notional across all alerts in window
- `dominant_expiries`, `dominant_strikes` — top 3 by alert count
- `flow_acceleration` — "accelerating" | "steady" | "decelerating" | "insufficient_data"
- `top_alerts` — top 3 alerts by priority score
- `narrative` — 2–4 sentence plain-language summary

**Flow acceleration heuristic:**
```
Requires ≥ 6 alerts. Split window into thirds by time.
late / early ratio ≥ 1.5  → "accelerating"
late / early ratio ≤ 0.67 → "decelerating"
otherwise                  → "steady"
```

**API:**
```
GET /api/v1/intelligence/flow-story/SPY?hours=8
GET /api/v1/intelligence/flow-story?hours=8&top_n=5   (multi-symbol, most active)
```

---

## How to Use

### Run the migration
```bash
cd backend
alembic upgrade 007
```

### Test the endpoints
```bash
# Ranked alerts (last 24h, by priority)
curl http://localhost:8000/api/v1/intelligence/alerts-ranked?hours=24&limit=10

# Pattern detection (last 6h)
curl http://localhost:8000/api/v1/intelligence/patterns?hours=6

# Flow story for SPY (last 8h)
curl http://localhost:8000/api/v1/intelligence/flow-story/SPY?hours=8

# Top 5 symbols' stories (last 8h)
curl http://localhost:8000/api/v1/intelligence/flow-story?hours=8&top_n=5
```

### Set a symbol priority
```bash
# Mark SPY as a core watchlist symbol with 2× ranking weight
curl -X PUT http://localhost:8000/api/v1/tenants/00000000-0000-0000-0000-000000000001/signal-settings/symbols/SPY \
  -H "Content-Type: application/json" \
  -d '{"priority_weight": 2.0, "watchlist_tier": "core"}'
```

---

## What's in v2 (deferred)

| Feature | Why deferred |
|---------|-------------|
| Sweep detection | Requires tick-level data, not available with delayed snapshots |
| Pattern persistence + push | Storage and notification infrastructure needed |
| Cross-symbol correlation | Needs sufficient concurrent alert history |
| Flow story delta (vs prior session) | Needs session concept + prior session storage |
| Pattern confidence calibration | Needs labeled ground truth to calibrate strength scores |
| Frontend pages for ranking/patterns/flow | Planned but de-scoped from v1 to keep scope tight |
| ML-based clustering | Explicitly out of scope for this product layer |

---

## Design Principles

1. **All heuristics are explicit and documented.** No black boxes.
2. **Scores are on the same 0–10 scale as anomaly_score** where possible — the user doesn't need to learn a new scale.
3. **Nothing breaks backward compatibility.** All new fields are nullable. Existing pipeline behavior is unchanged.
4. **Priority score ≠ anomaly score.** Anomaly score measures statistical deviation. Priority score measures actionability (adds economic size, quality, and client preference). They serve different purposes.
5. **Patterns are advisory.** They flag structure; they don't replace the underlying alert quality assessment.
