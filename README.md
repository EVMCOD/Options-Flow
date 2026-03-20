# Options Flow Radar

A professional B2B options flow scanner and alert engine. Ingests real-time options chain data, computes volume anomaly signals, and surfaces high-conviction unusual activity through a live dashboard.

**Who it's for:** Quantitative traders, prop desks, and fintech teams that need a self-hosted, extensible pipeline for detecting unusual options activity — without locking into a third-party black box.

---

## Architecture

```
┌──────────────┐     ┌────────────────────┐     ┌──────────────────────┐
│ Data Provider │────▶│  Ingestion Service  │────▶│  Raw Option Snapshot │
│ (mock/CBOE/  │     │  (run_ingestion)    │     │  (PostgreSQL JSON)   │
│  Tradier/…)  │     └─────────┬──────────┘     └──────────────────────┘
└──────────────┘               │ normalize
                               ▼
                  ┌────────────────────────┐
                  │ Normalized Snapshot     │
                  │ (normalized_option_     │
                  │  snapshots table)       │
                  └────────────┬───────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │  Signal Engine          │
                  │  (volume_ratio,         │
                  │   z-score, anomaly      │
                  │   score computation)    │
                  └────────────┬───────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
          ┌──────────────────┐  ┌──────────────────┐
          │  Signal Feature   │  │  Alert            │
          │  (signal_features │  │  (alerts table)   │
          │   table)          │  └────────┬──────────┘
          └──────────────────┘           │
                                         ▼
                               ┌──────────────────┐
                               │  FastAPI REST API │
                               └────────┬──────────┘
                                        │
                               ┌────────▼──────────┐
                               │  Next.js Dashboard │
                               │  (Overview, Alerts,│
                               │   Universe mgmt)   │
                               └───────────────────┘
```

**Architecture decision:** Modular monolith. Everything runs in one Python process per the `backend` container. The pipeline is split into discrete services (`ingestion.py`, `signal.py`) and jobs (`ingestion_job.py`, `signal_job.py`) that are independently testable and replaceable. There is no message queue — APScheduler drives the cycle. This keeps ops overhead minimal while remaining extensible.

---

## Project Structure

```
options-flow-radar/
├── backend/
│   ├── app/
│   │   ├── core/           # Config, DB engine, logging
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic v2 request/response schemas
│   │   ├── providers/      # Data provider abstraction + mock
│   │   ├── services/       # Business logic (ingestion, signal, universe)
│   │   ├── jobs/           # Runnable job wrappers
│   │   ├── routers/        # FastAPI route handlers
│   │   ├── scheduler.py    # APScheduler setup
│   │   └── main.py         # FastAPI app + lifespan
│   ├── migrations/         # Alembic migrations
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router pages
│   │   ├── components/     # UI, layout, feature components
│   │   ├── lib/            # API client, TypeScript types
│   │   └── hooks/          # usePolling custom hook
│   ├── package.json
│   └── Dockerfile
├── infra/postgres/         # DB init SQL
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Quick Start

### Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)

### Run

```bash
git clone <repo>
cd options-flow-radar
cp .env.example .env
docker-compose up --build
```

Docker Compose will:
1. Start PostgreSQL 16 and wait for the healthcheck
2. Build and start the backend — runs `alembic upgrade head` then launches uvicorn with hot-reload
3. Build and start the frontend

Once all three containers are healthy:

- **Dashboard:** http://localhost:3000
- **API docs:** http://localhost:8000/docs
- **Health check:** http://localhost:8000/api/v1/health

The backend seeds the scanner universe on first startup and fires an ingestion run 5 seconds after launch. Alerts will appear within ~30 seconds.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://ofr:ofr@localhost:5432/ofr` | Async PostgreSQL connection string |
| `ENV` | `development` | Controls log format (pretty vs JSON) |
| `LOG_LEVEL` | `INFO` | Python log level |
| `DATA_PROVIDER` | `mock` | Which provider to use (`mock` or custom) |
| `SCAN_INTERVAL_SECONDS` | `300` | Seconds between ingestion runs |
| `VOLUME_SPIKE_THRESHOLD` | `2.0` | Minimum volume_ratio to register as anomalous |
| `VOLUME_SPIKE_HIGH` | `4.0` | volume_ratio for HIGH tier heuristic |
| `ZSCORE_THRESHOLD` | `2.0` | Z-score threshold for anomaly detection |
| `MIN_VOLUME` | `100` | Contracts below this volume are ignored by the signal engine |
| `BASELINE_LOOKBACK_RUNS` | `20` | Past ingestion runs used to compute volume baseline |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL visible to the browser |

---

## Running Jobs Manually

Trigger a full ingestion + signal run:

```bash
curl -X POST http://localhost:8000/api/v1/jobs/run-ingestion
```

Trigger the signal engine only (uses the most recent successful run):

```bash
curl -X POST http://localhost:8000/api/v1/jobs/run-signal
```

Both endpoints return immediately and run the job in the background:

```json
{
  "success": true,
  "data": {
    "job_name": "ingestion_job",
    "triggered_at": "2025-01-15T10:00:00Z",
    "status": "triggered"
  }
}
```

---

## Data Flow

1. **Fetch** — The ingestion service calls `provider.fetch_chain(symbol)` for each enabled symbol. The mock provider returns realistic option chains with injected volume spikes.

2. **Raw storage** — Each `OptionContract` is stored as a `RawOptionSnapshot` (JSON blob). This is the audit trail — raw data is preserved before any transformation.

3. **Normalize** — Each contract is mapped to a `NormalizedOptionSnapshot` with typed columns (strike as `Numeric`, expiry as `Date`, etc.). The normalized table is what the signal engine reads.

4. **Compute features** — For each snapshot, the signal engine:
   - Fetches historical volumes for the same (symbol, expiry, strike, type) from the last `BASELINE_LOOKBACK_RUNS` runs
   - Computes `baseline_volume`, `volume_ratio`, `volume_zscore`, `volume_oi_ratio`, `premium_proxy`
   - Computes `anomaly_score` (see Signal Logic below)
   - Persists a `SignalFeature` row

5. **Generate alerts** — Snapshots exceeding score thresholds get an `Alert` row with a human-readable explanation and level badge.

6. **Serve** — FastAPI exposes REST endpoints for all data. The Next.js frontend polls `/alerts`, `/metrics/summary`, and `/universe` every 30 seconds.

---

## Signal Logic

### Volume Baseline

For each (symbol, expiry, strike, option_type) tuple, the engine looks back at the last `BASELINE_LOOKBACK_RUNS` successful ingestion runs and computes `mean` and `std` of historical volumes using NumPy.

If fewer than 3 historical runs exist (early startup), a floor baseline of `max(50, open_interest * 0.02)` is used.

### Features

| Feature | Formula |
|---|---|
| `volume_ratio` | `current_volume / baseline_volume` |
| `volume_zscore` | `(current_volume - mean) / std` |
| `volume_oi_ratio` | `current_volume / open_interest` |
| `premium_proxy` | `volume × (bid + ask) / 2 × 100` (dollar proxy assuming 100-share multiplier) |

### Anomaly Score (0–10 scale)

```
norm_ratio = clamp(volume_ratio / 10, 0, 1)
norm_z     = clamp(|zscore| / 5, 0, 1)
norm_voi   = clamp(volume_oi_ratio / 0.5, 0, 1)

anomaly_score = (0.40 × norm_ratio + 0.40 × norm_z + 0.20 × norm_voi) × 10
```

### Alert Thresholds

| Score | Level |
|---|---|
| ≥ 7.0 | CRITICAL |
| ≥ 5.0 | HIGH |
| ≥ 3.0 | MEDIUM |
| ≥ 1.5 | LOW |
| < 1.5 | (no alert) |

---

## Connecting a Real Provider

1. Create a new file `backend/app/providers/my_provider.py`
2. Implement `BaseOptionsDataProvider`:

```python
from app.providers.base import BaseOptionsDataProvider, OptionContract

class MyProvider(BaseOptionsDataProvider):
    def provider_name(self) -> str:
        return "my_provider"

    async def fetch_chain(self, symbol: str) -> list[OptionContract]:
        # Call your data source (CBOE DataShop, Tradier, Polygon, etc.)
        # Map the response to OptionContract dataclasses
        ...
```

3. Register it in `backend/app/jobs/ingestion_job.py`:

```python
def _get_provider():
    if settings.DATA_PROVIDER == "my_provider":
        return MyProvider()
    ...
```

4. Set `DATA_PROVIDER=my_provider` in your `.env`.

No other changes are needed — the ingestion service, signal engine, and routers are all provider-agnostic.

---

## Next Steps

- **WebSocket live feed** — Replace 30-second polling with a WebSocket endpoint (`/ws/alerts`) for true real-time delivery.
- **Auth / multi-tenant** — Add JWT authentication (FastAPI Users) and per-tenant universe isolation.
- **Real provider integration** — Wire up Tradier, Polygon.io, or CBOE DataShop to replace the mock.
- **IV surface tracking** — Store IV by (symbol, expiry, strike) over time to compute `iv_change` and detect IV crush/expand events.
- **Historical replay** — Add a job that can replay any date range from stored `RawOptionSnapshot` records to back-test signal parameters.
- **Alert webhooks** — POST CRITICAL/HIGH alerts to Slack, PagerDuty, or a custom webhook URL.
- **Backtesting harness** — Compare signal hits against next-day returns to validate anomaly_score predictiveness.
