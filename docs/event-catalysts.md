# Event Catalysts — Options Flow Radar

## What this is

The event catalyst layer adds upcoming-event context to alerts.

Without it the system says: *"unusual flow in SPY 550C"*.
With it it says: *"unusual flow in SPY 550C — Earnings in 3 days"*.

The difference matters.  Unusual flow before earnings is actionable.
The same flow on a random Tuesday is noise.

---

## Data model

### `symbol_events` table

| Column       | Type         | Notes |
|--------------|--------------|-------|
| `id`         | UUID         | Primary key |
| `tenant_id`  | UUID / NULL  | NULL = global, visible to all tenants |
| `symbol`     | VARCHAR(20)  | Uppercase, e.g. "AAPL" |
| `event_type` | VARCHAR(50)  | See supported types below |
| `title`      | VARCHAR(255) | Human-readable label |
| `event_date` | DATE         | When the event occurs |
| `event_time` | VARCHAR(10)  | Optional: "AMC", "BMO", "intraday", or "HH:MM" |
| `source`     | VARCHAR(100) | Where the date came from (optional) |
| `notes`      | TEXT         | Free-form context (optional) |
| `created_at` | TIMESTAMPTZ  | Auto-set at insert |
| `updated_at` | TIMESTAMPTZ  | Set explicitly on PATCH |

### Supported event types

| `event_type`     | Meaning | Boost class |
|------------------|---------|-------------|
| `earnings`       | Quarterly earnings release | **High** |
| `fda_decision`   | FDA approval/rejection decision | **High** |
| `pdufa`          | PDUFA date (drug review deadline) | **High** |
| `regulatory`     | Other regulatory milestone | Standard |
| `investor_day`   | Investor day / analyst day | Standard |
| `product_event`  | Product launch, WWDC, etc. | Standard |
| `macro_relevant` | Fed meeting, CPI, NFP if relevant | Standard |
| `custom`         | Anything else; uses `title` as the label | Standard |

### Scope: global vs tenant-specific

- `tenant_id = NULL` → visible to all tenants ("global" event).  Use this for shared earnings calendars.
- `tenant_id = <uuid>` → only visible to that tenant.  Use for proprietary catalysts.

When the signal engine resolves event context it returns events matching the current tenant **OR** global events.  A global event is never returned twice.

---

## How it enriches alerts

When the signal engine creates an alert, it looks up the nearest upcoming event for the alert's symbol.  If an event is found, four fields are populated on the alert record:

| Alert field       | Example value |
|-------------------|--------------|
| `catalyst_context` | `"Earnings in 3 days"` |
| `days_to_event`   | `3` |
| `next_event_type` | `"earnings"` |
| `next_event_date` | `"2026-04-22"` |

These are stored **denormalised** at alert creation time.  Even if the event is later edited or deleted, the alert retains the snapshot it saw.

The catalyst also appears inside `contributing_factors_json` under a `"catalyst"` key:
```json
{
  "catalyst": {
    "event_type": "earnings",
    "event_date": "2026-04-22",
    "days_to_event": 3,
    "context": "Earnings in 3 days",
    "boost_applied": 1.21
  }
}
```

---

## Priority score boost

When an event is within 7 days, the computed `priority_score` is multiplied by a boost factor **before** the HIGH/CRITICAL priority gates are evaluated.  This means:

- An event-adjacent signal with borderline priority may cross the HIGH/CRITICAL gate it would otherwise miss.
- The boost is context, not fabrication — it only elevates scores that already have a real signal behind them.

### Boost table

| Days to event | High-impact types* | All other types |
|---------------|-------------------|----------------|
| 0 – 1         | ×1.30             | ×1.15          |
| 2 – 3         | ×1.21             | ×1.105         |
| 4 – 7         | ×1.12             | ×1.06          |
| > 7           | ×1.00 (no boost)  | ×1.00          |

\* High-impact: `earnings`, `fda_decision`, `pdufa`

Boosted scores are capped at 10.0.

---

## API endpoints

Base path: `/api/v1/events`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/events` | Create an event |
| `GET`  | `/events` | List events (filterable) |
| `GET`  | `/events/upcoming` | Next event per symbol in scanner universe |
| `GET`  | `/events/{id}` | Get a single event |
| `PATCH`| `/events/{id}` | Update an event |
| `DELETE`| `/events/{id}` | Delete an event |

### Query params for `GET /events`

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `symbol` | string | — | Filter by symbol |
| `event_type` | string | — | Filter by type |
| `upcoming_only` | bool | false | Only future events |
| `days_ahead` | int | — | Limit to next N days |
| `limit` | int | 100 | Max results |
| `offset` | int | 0 | Pagination |

### Example: add an earnings event

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "event_type": "earnings",
    "title": "AAPL Q2 2026 Earnings",
    "event_date": "2026-04-30",
    "event_time": "AMC",
    "source": "earnings_whispers"
  }'
```

### Example: view upcoming catalysts for the universe

```bash
curl http://localhost:8000/api/v1/events/upcoming
```

Response:
```json
{
  "success": true,
  "data": [
    {
      "symbol": "NVDA",
      "event_type": "earnings",
      "title": "NVDA Q1 2026 Earnings",
      "event_date": "2026-05-28",
      "days_to_event": 2,
      "catalyst_context": "Earnings tomorrow",
      "is_near": true
    }
  ]
}
```

---

## Workflow: first setup

Since v1 has no automatic provider, populate events manually:

```bash
# Bulk add earnings dates (repeat for each symbol)
for payload in \
  '{"symbol":"SPY","event_type":"macro_relevant","title":"FOMC Rate Decision","event_date":"2026-04-07","event_time":"14:00"}' \
  '{"symbol":"AAPL","event_type":"earnings","title":"AAPL Q2 Earnings","event_date":"2026-04-30","event_time":"AMC"}' \
  '{"symbol":"NVDA","event_type":"earnings","title":"NVDA Q1 Earnings","event_date":"2026-05-28","event_time":"AMC"}' \
  '{"symbol":"TSLA","event_type":"earnings","title":"TSLA Q1 Earnings","event_date":"2026-04-22","event_time":"AMC"}'
do
  curl -s -X POST http://localhost:8000/api/v1/events \
    -H "Content-Type: application/json" \
    -d "$payload"
done
```

To update a date (e.g. confirmed earnings moved):
```bash
curl -X PATCH http://localhost:8000/api/v1/events/<event_id> \
  -H "Content-Type: application/json" \
  -d '{"event_date": "2026-05-01"}'
```

---

## Limitations of v1

1. **Manual entry only.** No automatic calendar provider.
2. **No deduplication guard.** You can insert the same event twice — check first with `GET /events?symbol=AAPL&upcoming_only=true`.
3. **No historical backfill.** Alerts created before an event was added will not have `catalyst_context` populated.
4. **Boost affects ALL levels equally.** There is no per-level cap on how much a boost can affect a score.

---

## V2 roadmap (future work)

| Feature | Description |
|---------|-------------|
| Auto-sync provider | Nightly job pulling from a calendar API (e.g. Earnings Whispers, AlphaQuery, SEC EDGAR for PDUFA) |
| Dedup on upsert | `POST /events` with `upsert=true` that updates if same symbol+date+type exists |
| Per-event boost override | `boost_weight` field on `symbol_events` to tune catalyst impact per event |
| Past-event suppression | Automatically downgrade boost if event date has passed (today > event_date) |
| Frontend calendar view | Show upcoming catalysts alongside the flow story for each symbol |
