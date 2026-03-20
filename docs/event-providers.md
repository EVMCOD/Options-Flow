# Event Provider Architecture

## Overview

The event provider system is a pluggable layer for fetching and persisting upcoming
event catalysts (earnings, FDA decisions, macro events) into `symbol_events`.

```
POST /api/v1/jobs/sync-events
          │
          ▼
  events_job.run_events_sync_job()
          │  resolves symbols from ScannerUniverse if not passed
          ▼
  events/service.sync_events()
          │  routes to matching providers
          │
     ┌────┴────────────────────────┐
     ▼                             ▼
YFinanceEarningsProvider    (future providers)
  fetch(symbols)
     │
     ▼
  ProviderFetchResult
  [ ProviderEvent, ... ]
          │
          ▼
  Conflict Policy (per event)
          │
          ▼
  DB write (SymbolEvent)
```

---

## Files

| File | Purpose |
|------|---------|
| `app/events/providers/base.py` | `ProviderEvent` dataclass + `BaseEventProvider` ABC |
| `app/events/providers/yfinance_earnings.py` | Yahoo Finance earnings (live) |
| `app/events/providers/regulatory.py` | FDA/PDUFA scaffold (not implemented) |
| `app/events/service.py` | Orchestrator, provider registry, conflict policy |
| `app/jobs/events_job.py` | Job runner — opens its own DB session |
| `app/scheduler.py` | Registers daily CronTrigger at 06:00 UTC |
| `app/routers/jobs.py` | `POST /jobs/sync-events` and `POST /jobs/sync-earnings` |

---

## Conflict Policy

For each event returned by a provider, the service applies these rules **in order**:

| Rule | Condition | Action |
|------|-----------|--------|
| 1 | Exact match: `(tenant_id\|NULL, symbol, event_type, event_date)` | **skip** |
| 2 | Near-date drift: same `(symbol, event_type)`, within ±30 days, `source != "manual"` | **update** `event_date`, `source`, `notes` |
| 3 | Near-date drift: same as rule 2 but `source == "manual"` | **skip** — user owns it |
| 4 | No match | **create** new row |

Rule 2 exists because earnings dates shift by a few days between announcement and
confirmation. Without it, re-running creates duplicates a week apart.

Rule 3 guarantees that manual entries created via `POST /events` or
`PATCH /events/{id}` are never silently overwritten by a provider.

---

## Provider Contract

```python
class BaseEventProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    # Short stable identifier. Written to SymbolEvent.source.
    # Examples: "yfinance", "benzinga", "fda_calendar"

    @property
    @abstractmethod
    def supported_types(self) -> List[str]: ...
    # Event types this provider can supply.
    # Examples: ["earnings"], ["fda_decision", "pdufa"]

    @abstractmethod
    async def fetch(self, symbols: List[str]) -> ProviderFetchResult: ...
    # MUST NOT raise. MUST NOT write to DB.
    # Return .events (may be empty) + .errors (empty on success).
```

---

## Adding a New Provider

1. Create `app/events/providers/my_provider.py`:

```python
from app.events.providers.base import BaseEventProvider, ProviderEvent, ProviderFetchResult

class MyProvider(BaseEventProvider):
    @property
    def name(self) -> str:
        return "my_provider"           # stable, lowercase, no spaces

    @property
    def supported_types(self) -> List[str]:
        return ["earnings"]            # or your custom event types

    async def fetch(self, symbols: List[str]) -> ProviderFetchResult:
        result = ProviderFetchResult()
        for sym in symbols:
            try:
                # ... call external API ...
                result.events.append(ProviderEvent(
                    symbol=sym,
                    event_type="earnings",
                    event_date=some_date,
                    title=f"{sym} Earnings",
                ))
            except Exception as exc:
                result.errors.append(f"{sym}: {exc}")
        return result
```

2. Register it in `app/events/service.py`:

```python
from app.events.providers.my_provider import MyProvider

_PROVIDERS: List[BaseEventProvider] = [
    YFinanceEarningsProvider(),
    MyProvider(),                      # ← add here
]
```

That's it. The service, job runner, scheduler, and API endpoint pick it up
automatically on next restart.

---

## API Usage

### Sync all events (default providers, all symbols in universe)

```
POST /api/v1/jobs/sync-events
```

### Sync earnings only

```
POST /api/v1/jobs/sync-events?types=earnings
```

### Sync specific symbols

```
POST /api/v1/jobs/sync-events?symbols=AAPL,NVDA,TSLA
```

### Sync with a specific provider

```
POST /api/v1/jobs/sync-events?providers=yfinance
```

### Response

```json
{
  "success": true,
  "data": {
    "providers_run": 1,
    "results": [
      {
        "provider": "yfinance",
        "created": 5,
        "updated": 1,
        "skipped": 2,
        "failed": 0,
        "errors": []
      }
    ]
  }
}
```

---

## Bootstrap

First run — seed the symbol universe, then sync:

```bash
# 1. Run migrations (creates symbol_events table)
alembic upgrade head

# 2. (Optional) Seed known events manually
python scripts/seed_events.py

# 3. Sync via Yahoo Finance
curl -X POST http://localhost:8000/api/v1/jobs/sync-events
```

---

## Scheduler

`events_sync_daily` fires at **06:00 UTC** daily (before US pre-market).

```python
# app/scheduler.py
scheduler.add_job(
    run_events_sync_job,
    trigger=CronTrigger(hour=6, minute=0, timezone="UTC"),
    id="events_sync_daily",
    misfire_grace_time=300,
)
```

If the server was down at :00, APScheduler fires the job within 5 minutes of
restart (grace period).

---

## Observability

Every `run_events_sync_job` call emits structured logs:

| Event | Key fields |
|-------|-----------|
| `events_job.start` | `tenant_id`, `symbol_count`, `types`, `providers` |
| `yfinance_earnings.found` | `symbol`, `event_date`, `confidence` |
| `events_service.created` | `symbol`, `event_type`, `event_date`, `source` |
| `events_service.drift_updated` | `symbol`, `old_date`, `new_date` |
| `events_service.exact_match_skip` | `symbol`, `event_type`, `event_date` |
| `events_service.manual_source_skip` | `symbol`, `existing_date`, `provider_date` |
| `events_job.complete` | `providers_run`, `created`, `updated`, `skipped`, `failed`, `errors` |

---

## V2 Roadmap

- `RegulatoryEventProvider` — FDA PDUFA dates (see `regulatory.py` scaffold)
- `MacroEventProvider` — FOMC, CPI, PCE dates from the Fed calendar
- Confidence threshold filter — skip events below a configurable confidence score
- Backfill on alert creation — if a new alert fires with no events seeded,
  auto-trigger a targeted sync for that symbol
