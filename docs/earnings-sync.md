# Earnings Sync — Operations Guide

## Source chosen: Yahoo Finance via yfinance

**Why yfinance:**
- Zero-config — no API key, no registration
- Well-maintained Python package (not raw scraping)
- `ticker.calendar["Earnings Date"]` gives the announced upcoming date window reliably for US equities
- Sufficient for a small universe (10–50 symbols), each fetch ~0.5 s
- v2 can swap to a structured API (see below) without touching callers

**Limitations:**
- Yahoo Finance does not guarantee BMO/AMC timing (event_time is always NULL after sync — set manually)
- Rate-limited at high frequency; fine for a nightly job, not for real-time polling
- Historical accuracy is good for large-cap; less reliable for small-cap, crypto, ETFs
- Calendar dates are estimates until formally announced; `notes` field reflects this
- yfinance ToS is informal — Yahoo may break the API without notice (mitigated by the fallback + manual seed)

**Fallback:** if yfinance fails or is unavailable, use the manual seed workflow (`scripts/seed_events.py`) with `data/earnings_seed.json` as a baseline.

---

## Bootstrap — first-time setup

```bash
# 1. Apply migrations (required once)
cd backend
alembic upgrade head

# 2. Install yfinance (optional but enables auto-sync)
pip install yfinance>=0.2.38

# 3a. Auto-sync from Yahoo Finance (requires yfinance)
curl -X POST "http://localhost:8000/api/v1/jobs/sync-earnings"
# or specific symbols:
curl -X POST "http://localhost:8000/api/v1/jobs/sync-earnings?symbols=AAPL,NVDA,TSLA,META"

# 3b. OR seed from JSON file (no yfinance needed)
python scripts/seed_events.py

# 4. Backfill catalyst context onto existing alerts
curl -X POST "http://localhost:8000/api/v1/events/backfill-alerts"

# 5. Run diagnostic to confirm everything works
python scripts/check_events.py
```

---

## Nightly sync job

The sync endpoint is idempotent — safe to call repeatedly. Configure a cron or scheduler entry:

```bash
# cron example (every day at 06:00)
0 6 * * * curl -s -X POST http://localhost:8000/api/v1/jobs/sync-earnings >> /var/log/earnings_sync.log 2>&1
```

Or integrate with APScheduler (already in the project):

```python
# In app/scheduler.py — add to the existing scheduler setup:
scheduler.add_job(
    _run_earnings_sync_all_tenants,
    "cron",
    hour=6,
    minute=0,
    id="earnings_sync_daily",
    replace_existing=True,
)
```

Where `_run_earnings_sync_all_tenants` is a job function that:
1. Opens a DB session
2. Reads the scanner universe
3. Calls `sync_earnings(db, sym_list, default_tenant_id)`

---

## Manual workflow (no yfinance)

Edit `backend/data/earnings_seed.json` and run:

```bash
python scripts/seed_events.py
# or
python scripts/seed_events.py path/to/my_events.json --api-url http://localhost:8000
```

The seed file format:
```json
[
  {
    "symbol": "NVDA",
    "event_type": "earnings",
    "title": "NVDA Q1 FY2027 Earnings",
    "event_date": "2026-05-28",
    "event_time": "AMC",
    "source": "ir.nvidia.com",
    "notes": "Confirmed"
  }
]
```

Valid `event_type` values: `earnings`, `fda_decision`, `pdufa`, `regulatory`,
`investor_day`, `product_event`, `macro_relevant`, `custom`.

---

## Setting event_time (BMO/AMC)

yfinance does not expose timing. Set it manually after sync:

```bash
# PATCH /events/{id}  — get the ID from GET /events?symbol=NVDA
curl -X PATCH "http://localhost:8000/api/v1/events/{id}" \
  -H "Content-Type: application/json" \
  -d '{"event_time": "AMC"}'
```

Or use the Events UI → click the event → edit timing.

---

## Backfill existing alerts

Alerts created before events were seeded have NULL catalyst fields. The backfill
endpoint re-enriches them using today's event context:

```bash
curl -X POST "http://localhost:8000/api/v1/events/backfill-alerts"
# → { "updated": 47, "skipped": 12 }
```

**Caveat:** `days_to_event` is computed from today, not the original alert fire time.
Only use this for catch-up; going forward, the signal engine enriches at creation time.

---

## What happens if the source fails

1. `sync-earnings` returns `{ errors: ["NVDA: ..."] }` for failed symbols; successful ones are still committed
2. Other symbols in the batch are unaffected (per-symbol try/except)
3. Fall back to the manual seed workflow for the failed symbols
4. Existing events in the DB are never deleted by the sync — stale entries stay until manually removed

---

## V2 roadmap

| Improvement | Why |
|---|---|
| FMP / Alpha Vantage as primary source | More reliable BMO/AMC, cleaner API, official ToS |
| Multiple date confirmations | Announced → confirmed → confirmed with time |
| FDA PDUFA calendar | Scrape FDA website or use Evaluate Pharma API |
| Universe-wide event heatmap | Dashboard widget showing event density by week |
| Per-event notes from earnings call transcripts | LLM-based summary |
| Webhook/notification on T-1 | Alert digest with upcoming catalysts |

The service layer (`app/services/earnings_sync.py`) is designed for easy source
swapping — just replace `_get_next_earnings_date()` with an alternative implementation.
