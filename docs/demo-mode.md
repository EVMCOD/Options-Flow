# Demo Mode

A standalone demo server that serves the full API contract with curated fixture data.
Zero database. Zero scanner. No API keys. No providers.

---

## Architecture

```
demo/
  server.py        ← standalone FastAPI app (single file, ~500 lines)
  requirements.txt ← fastapi + uvicorn only
  Procfile         ← Render start command
```

The frontend is **unchanged**. The demo just points `NEXT_PUBLIC_API_URL` at the
demo server instead of the real backend. Everything else — routing, polling,
rendering — is identical.

```
Frontend (Vercel / Render static)
         │  NEXT_PUBLIC_API_URL
         ▼
demo/server.py   ←  curated fixture data, dynamic dates
         │
         ✗  no database
         ✗  no scanner
         ✗  no yfinance
         ✗  no provider credentials
```

**Why not DEMO_MODE in the real backend?**

Keeping it separate avoids mixing fixture logic into production code, keeps the real
backend clean, and makes the demo truly independent — it can be deployed even when
the real backend is broken or being refactored.

---

## Running locally

```bash
cd demo
pip install -r requirements.txt
uvicorn server:app --reload --port 8001
```

Then set the frontend to point at it:

```bash
# In frontend/.env.local (or export before starting Next.js)
NEXT_PUBLIC_API_URL=http://localhost:8001
```

Start the frontend:

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000`.

---

## Deploying on Render (recommended)

Render will host the demo API as a free Web Service. It takes ~3 minutes.

### Step 1 — Create a new Web Service

- Connect your GitHub repo
- **Root Directory:** `demo`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
- Environment: Python 3

### Step 2 — Configure the frontend

On your frontend service (Render or Vercel), add or update:

```
NEXT_PUBLIC_API_URL=https://<your-demo-api-name>.onrender.com
```

That's it. The frontend will call the demo API and display the curated data.

### Free tier note

Render free tier spins down after 15 minutes of inactivity. The first request
after a cold start takes ~30 seconds. To avoid this in a live demo:
- Keep a browser tab open on the app for at least a minute before showing it
- Or upgrade to the Starter plan ($7/month) which has no spin-down

---

## What the demo data shows

The fixture data is designed to tell the product story clearly. Dates are computed
dynamically from `date.today()` on startup — "Earnings in 6 days" always means
6 days from the moment the server starts.

### Events (upcoming catalysts)

| Symbol | Event | Days from now |
|--------|-------|--------------|
| SPY / QQQ | FOMC Rate Decision | 5 days |
| NVDA | Q1 Earnings (AMC) | 6 days |
| TSLA | Q1 Earnings (AMC) | 7 days |
| AAPL | Q2 Earnings (AMC) | 14 days |
| META | Q1 Earnings (AMC) | 21 days |
| AMD | Q1 Earnings (AMC) | 39 days |
| MSFT | Q3 Earnings (AMC) | 40 days |

### Alerts (15 total)

| # | Symbol | Contract | Level | Priority | Story |
|---|--------|----------|-------|---------|-------|
| 1 | NVDA | 820C | CRITICAL | 8.9 | 10.2× vol, 3rd consecutive session, earnings in 6 days |
| 2 | TSLA | 285C | CRITICAL | 8.4 | Block trade, 7.8× vol, earnings in 7 days |
| 3 | SPY  | 560P | HIGH | 7.6 | Put surge, FOMC in 5 days, corroborated by QQQ |
| 4 | AAPL | 230C | HIGH | 7.1 | Call sweep, earnings in 14 days |
| 5 | META | 700C | HIGH | 6.8 | Block trade, earnings in 21 days |
| 6 | AMD  | 135C | HIGH | 6.3 | Cross-exchange sweep, no catalyst |
| 7 | QQQ  | 475P | MEDIUM | 5.4 | Macro hedge corroborating SPY puts |
| 8 | MSFT | 430C | MEDIUM | 5.1 | Light call activity, no catalyst |
| 9 | NVDA | 780P | MEDIUM | 4.8 | Protective put alongside call sweep — straddle build |
| 10 | AAPL | 210P | MEDIUM | 4.5 | Near-term put, expires before earnings |
| 11 | AMD  | 125P | MEDIUM | 4.2 | Light put, no catalyst |
| 12 | META | 660P | LOW | 3.8 | Acknowledged |
| 13 | MSFT | 410P | LOW | 3.4 | Dismissed |
| 14 | TSLA | 265P | LOW | 3.2 | Acknowledged — minor puts near TSLA earnings |
| 15 | SPY  | 570C | LOW | 3.0 | Active — contrasting call vs dominant put flow |

### Product story the data tells

1. **Smart ranking** — NVDA is #1 not because of raw volume, but because of
   volume + catalyst + repeat pattern = rare confluence. AMD is #6 with similar
   volume but no catalyst, so it ranks lower.

2. **Catalyst integration** — NVDA alert shows "Earnings in 6 days (AMC)" inline.
   The detail view shows exactly how the earnings boost was applied (×1.45 to
   priority score).

3. **Pattern detection** — NVDA 820C has a `repeat_strike` tag and the explanation
   says "3rd consecutive session." The patterns endpoint surfaces this as a
   `repeated_prints` pattern with strength 0.94.

4. **Rich explanations** — Not "volume spike detected." Instead: "10.2× normal
   volume... third consecutive session... $12.0M notional... institutional scale...
   catalyst: NVDA earnings in 6 days."

5. **Macro hedging story** — SPY puts + QQQ puts both flagged and linked by the
   `strike_cluster` pattern. Shows cross-symbol intelligence.

6. **Workflow demo** — LOW/acknowledged/dismissed alerts show the full alert
   lifecycle. The default view (active-only) is clean; you can show "show all"
   to demonstrate it.

---

## Write operations

All mutations succeed in-memory and reset on server restart. This lets you
interact with every form (add universe symbol, create event, update settings)
without errors during a demo. The data resets cleanly on the next restart.

---

## What's demo-only vs real

| Behavior | Demo server | Real backend |
|----------|------------|--------------|
| Data source | Fixture data in `server.py` | PostgreSQL + scanner |
| API contract | Identical | Same |
| Write ops | In-memory (resets on restart) | Persistent |
| Scanner | None — no ingestion runs | Real-time, scheduled |
| yfinance sync | No-op | `POST /jobs/sync-events` |
| Patterns | Hardcoded | Computed from real alert history |
| Flow stories | Hardcoded narratives | Computed from signal data |
| Dates | `date.today() + offset` on startup | Actual alert timestamps |

---

## Switching back to the real backend

Change `NEXT_PUBLIC_API_URL` back to the real backend URL (e.g.
`https://ofr-api.onrender.com`) and redeploy the frontend. The demo server
can keep running independently — it doesn't affect the real system at all.

---

## Updating the demo data

All fixture data lives in `demo/server.py` under `_build_alerts()`,
`_EVENT_SCHEDULE`, and `_build_universe()`. Edit those functions and
redeploy the demo service. No database migrations needed.

To change an alert's narrative or add a new symbol event: edit `server.py`,
push to git, Render auto-deploys.
