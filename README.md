# WindSight — UK Wind Generation Forecast Intelligence

WindSight answers one procurement question with real Elexon data:

> **What did the wind forecast say when the day-ahead trading decision had to be
> made, and how far did it miss actual generation?**

It ingests two official Elexon BMRS datasets, stores them durably, reconstructs the
forecast that was *eligible at the decision cutoff*, matches it to actual half-hourly
outturn, and reports error metrics, coverage and provenance in a React application.

Evaluation period: **1–31 January 2026** (delivery dates). Read-only public demo, no
registration.

---

## 1. Live application

| Surface | URL |
| --- | --- |
| Web application (Vercel) | `__PASTE_VERCEL_URL_HERE__` |
| API service (Render / Heroku) | `__PASTE_API_URL_HERE__` |

Those two placeholders are the only details left to fill in. Until they are
replaced, the application runs locally with the commands below; every figure in
this README was produced from that local run against real Elexon data.

---

## 2. Quick start

### Docker (one command)

```bash
docker compose up -d --build
```

- Application: <http://localhost:3000>
- API documentation: <http://localhost:8000/docs>
- Health check: <http://localhost:3000/api/health>

The container creates the database schema, imports the committed real Elexon
snapshot when the database is empty, and only then reports healthy. Full detail:
section 9.

### Without Docker

```bash
# terminal 1 - API
cd backend
python -m venv .venv
source .venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m app.scripts.import_historical_data --source snapshot   # or --source live
uvicorn app.main:app --reload --port 8000

# terminal 2 - web app
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

Full detail: section 10.

---

## 3. What is in the product

| Page | Purpose |
| --- | --- |
| **Overview** | Period KPIs (MAE, RMSE, bias, MAPE), matched intervals, coverage, daily error trend. |
| **Forecast Explorer** | All 48 intervals for a delivery date: selected forecast, publication timestamp, actual, signed/absolute error, sortable table. |
| **Accuracy Analysis** | Daily accuracy table, error distributions, worst intervals, bias narrative, CSV export. |
| **Methodology & Data** | Cutoff policy, selection algorithm, metric definitions, data provenance, import history, exclusions. |
| **About the Developer** | Author and project context. |

Global control on every page: **decision cutoff time** (`07:30 … 18:30`) and
**cutoff day offset** (`D-1` / `D`). Changing either re-queries the backend; forecast
selection and every metric are recomputed — nothing is relabelled client-side.

---

## 4. Architecture

```
                    ┌──────────────────────────────────────────────┐
  Browser ────────► │ React 18 + Vite + TypeScript + Tailwind      │
                    │ react-router, recharts, lucide-react          │
                    └───────────────┬──────────────────────────────┘
                                    │ /api/*  (JSON, CSV)
                    ┌───────────────▼──────────────────────────────┐
                    │ FastAPI (Python 3.11)                        │
                    │  routes → AnalysisService → DatabaseStore    │
                    │  cutoff selection · matching · metrics        │
                    └───────────────┬──────────────────────────────┘
                                    │ SQLAlchemy 2 + Alembic
             ┌──────────────────────▼───────────────────────────┐
             │ Durable storage                                  │
             │  local/Docker: SQLite file on a named volume     │
             │  production:   managed PostgreSQL (same schema)  │
             └──────────────────────┬───────────────────────────┘
                                    │ one-off import CLI
             ┌──────────────────────▼───────────────────────────┐
             │ Elexon BMRS  FUELHH (actuals) · WINDFOR (fcsts)  │
             └──────────────────────────────────────────────────┘
```

Key property: **page loads never call Elexon.** They read the database, compute
selection and metrics in-process (memoised per cutoff/range), and return provenance.
The only write paths are the import CLI and the token-protected `POST /api/refresh`.

---

## 5. Data methodology

### 5.1 Sources

| Dataset | Use | Fields used |
| --- | --- | --- |
| `FUELHH` | Actual wind generation | `startTime`, `generation` (filtered to `fuelType=WIND`) |
| `WINDFOR` | Published wind forecasts | `startTime`, `publishTime`, `generation` |

- FUELHH: <https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream>
- WINDFOR: <https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream>
- API base used: `https://data.elexon.co.uk/bmrs/api/v1` (from the official OpenAPI spec).

### 5.2 Decision cutoff (configurable analytical assumption)

Default: **12:00 Europe/London on the calendar day before delivery (D-1)**.

- The cutoff instant is converted to UTC per delivery date, so the March/October DST
  transitions are handled by the timezone database rather than a fixed offset.
- Only forecasts with `publishTime <= cutoff` are eligible.
- The **latest eligible publication wins** per delivery interval.
- A forecast published *after* the cutoff is never used, even if it is more accurate.
- This is a defensible modelling assumption, **not** a verified market deadline; it is
  adjustable per request (`cutoff`, `cutoff_offset_days`) and via environment variables.

### 5.3 Selection and matching

1. Each delivery interval (`startTime`) is a half-hour slot: 48 per day.
2. Eligible forecasts for that slot are those published at or before the cutoff.
3. The maximum `publishTime` among them is selected and retained with its timestamp.
4. Actuals are joined **on delivery interval only** — never on publication time.
5. Missing actual or missing eligible forecast ⇒ `unmatched` with an explicit reason;
   missing values are never coerced to zero.

### 5.4 Metrics

With forecast `F`, actual `A`, error `e = F − A`:

| Metric | Definition | Interpretation |
| --- | --- | --- |
| MAE | `mean(|e|)` | headline accuracy, MW |
| RMSE | `sqrt(mean(e²))` | penalises large misses, MW |
| Bias | `mean(e)` | **positive = overforecast** |
| MAPE | `mean(|e/A|)×100` | only over non-zero actuals; excluded count reported |
| Median AE / P90 AE / Max AE | rank statistics | tail behaviour |
| Over / under / exact counts | sign of `e` | direction mix |

An empty sample returns `null`, never a misleading `0`.

### 5.5 Metric caveat shown in the UI

A near-zero bias does **not** imply accuracy: positive and negative errors can cancel
while individual misses stay large. The UI states this next to the bias figure.

---

## 6. Verified data coverage (real Elexon data)

Imported from the live BMRS API on **26 October 2026** and stored in the database:

| Item | Verified value |
| --- | --- |
| FUELHH actual rows | **1,488** (31 days × 48 intervals, no gaps) |
| WINDFOR forecast rows | **35,624** |
| Forecast publication range | 2025-12-02 02:30 UTC → 2026-01-31 22:30 UTC |
| Delivery coverage | **1,488 / 1,488** half-hourly intervals (100.0%) |
| Matched intervals | **1,488** |
| Missing actual / missing forecast | 0 / 0 |

Metrics at the default 12:00 D-1 cutoff:

| Metric | Value |
| --- | --- |
| MAE | **2,020.6 MW** |
| RMSE | **2,481.4 MW** |
| Bias | **+1,806.2 MW** (overforecast) |
| MAPE | **19.74%** (1,488 non-zero actuals, 0 excluded) |
| Median AE / P90 AE / Max AE | 1,711 / 4,025 / 6,885 MW |
| Over / under / exact | 1,271 / 217 / 0 |

Changing the cutoff to **09:30** (same day offset) re-selects earlier publications and
yields MAE 2,126.1 MW, RMSE 2,620.8 MW, bias +1,840.3 MW, MAPE 22.1% — proof that the
cutoff drives computation rather than labelling.

Real set-side note: January 2026 wind outturn in the dataset averages below the
day-ahead forecast, hence the large positive bias; this is a property of the data, not
of the UI.

### 6.1 Will I see the same data when I run it locally?

**Yes — the same records and the same metrics, without needing to fetch anything.**

The repository commits the real Elexon payloads that produced these numbers:

| File | Contents |
| --- | --- |
| `backend/data/snapshots/fuelhh.json` | every FUELHH `WIND` record for 1–31 Jan 2026 |
| `backend/data/snapshots/windfor.json` | every WINDFOR record published 2 Dec 2025 – 31 Jan 2026 |

On a fresh clone there is no database (`backend/data/windsight.db` is git-ignored). The
first time the API starts, it applies the Alembic migration and — because the database
is empty and `SEED_ON_STARTUP=true` — imports those snapshots as one recorded import run.
This was verified on a brand-new database file with live fetching disabled:

```
startup : {'ready': True, 'message': 'initial import completed from committed snapshots'}
records : 1488 actual / 35624 forecast
coverage: 1488 / 1488
metrics : n=1488 mae=2020.6 rmse=2481.4 bias=1806.2 mape=19.74
```

That is identical to the tables above. The same happens in Docker on a fresh volume.

What can differ:

- **Provenance label.** A snapshot-seeded database says `last import #N completed
  (snapshot)`; a live import says `(elexon_live)`. The figures are the same because the
  historical records are the same.
- **Live refresh.** Running
  `python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31`
  fetches from Elexon again. It is idempotent (re-inserts nothing), and if Elexon has
  since revised a published value, the stored row is updated in place.
- **Your cutoff choice.** The UI defaults to 12:00 D-1; selecting another cutoff
  deliberately changes the selected forecast versions and therefore the metrics.
- **Database engine.** SQLite locally versus PostgreSQL in production — same schema,
  same rows, same calculations.

Nothing is mocked or synthetic in the running application; the test suite mocks Elexon,
but the application itself only ever serves imported real records.

---

## 7. Repository layout

### 7.1 Directory tree

```
.
├── README.md                       this document
├── .env.example                    every supported variable, with defaults
├── .gitignore                      ignores .env, the SQLite DB, node_modules, dist
├── docker-compose.yml              backend + frontend, named volume, healthchecks
├── render.yaml                     Render blueprint: managed PostgreSQL + API service
│
├── backend/
│   ├── Dockerfile                  python:3.11-slim, non-root, /app/data volume, health gate
│   ├── Procfile                    Heroku process type (uvicorn on $PORT)
│   ├── requirements.txt            fastapi, uvicorn, httpx, pydantic, SQLAlchemy, Alembic, psycopg, pytest
│   ├── pytest.ini                  test configuration
│   ├── alembic.ini                 Alembic entry point
│   ├── alembic/
│   │   ├── env.py                  migration environment (reads DATABASE_URL)
│   │   ├── script.py.mako          revision template
│   │   └── versions/
│   │       └── 0001_initial_schema.py   the three application tables
│   ├── app/
│   │   ├── main.py                 app factory, startup migrate/seed, /api/health
│   │   ├── config.py               all settings from environment variables
│   │   ├── models.py               internal domain models (observations, metrics)
│   │   ├── service.py              analytics orchestration + memo cache
│   │   ├── store.py                DatabaseStore: read path, health, import runs
│   │   ├── importer.py             transactional, idempotent import + coverage checks
│   │   ├── source.py               data-source abstraction and errors
│   │   ├── export.py               CSV serialisation with provenance columns
│   │   ├── api/
│   │   │   ├── routes.py           every public endpoint
│   │   │   └── schemas.py          response contracts
│   │   ├── analysis/
│   │   │   ├── selection.py        cutoff-aware "latest eligible forecast" selection
│   │   │   ├── matching.py         forecast↔actual matching by delivery interval
│   │   │   ├── metrics.py          MAE, RMSE, bias, MAPE, quantiles
│   │   │   └── calendar.py         settlement days, half-hourly intervals, DST
│   │   ├── db/
│   │   │   ├── models.py           SQLAlchemy tables + constraints
│   │   │   ├── session.py          engine, sessions, URL resolution, ping
│   │   │   ├── repository.py       queries and idempotent upserts
│   │   │   └── migrations.py       programmatic `alembic upgrade head`
│   │   ├── elexon/
│   │   │   ├── client.py           BMRS client, windows, retries, response cache
│   │   │   └── normalize.py        payload validation and normalisation
│   │   └── scripts/
│   │       ├── import_historical_data.py   the import CLI (also --status)
│   │       └── show_status.py             status shortcut
│   ├── data/
│   │   ├── snapshots/fuelhh.json   committed real FUELHH payload (284 KB)
│   │   ├── snapshots/windfor.json  committed real WINDFOR payload (4.2 MB)
│   │   ├── cache/                  upstream response cache (git-ignored)
│   │   └── windsight.db            local SQLite database (git-ignored, created on first run)
│   └── tests/                      102 tests across 9 modules
│       ├── conftest.py             fixtures, mocked upstream, temp databases
│       ├── test_client.py          API client, windows, retries, failures
│       ├── test_normalize.py       payload validation and deduplication
│       ├── test_selection.py       cutoff eligibility and latest-eligible rule
│       ├── test_matching.py        interval matching, missing-data handling
│       ├── test_metrics.py         MAE/RMSE/bias/MAPE correctness
│       ├── test_service.py         end-to-end analytics
│       ├── test_api.py             HTTP contracts, CSV export, error shapes
│       ├── test_calendar.py        intervals, DST, date ranges
│       └── test_persistence.py     imports, idempotency, coverage, cache, DB failures
│
├── frontend/
│   ├── Dockerfile                  node build stage + unprivileged nginx runtime
│   ├── nginx.conf                  SPA fallback, /api proxy, security headers
│   ├── vercel.json                 Vercel build command, SPA rewrites, headers
│   ├── package.json                scripts: dev, build, test, typecheck, preview
│   ├── vite.config.ts              dev proxy to the API, Vitest configuration
│   ├── tsconfig.json               TypeScript compiler options
│   ├── index.html                  Vite HTML shell
│   ├── package-lock.json           locked dependency tree (used by `npm ci`)
│   └── src/
│       ├── main.tsx                React entry point
│       ├── App.tsx                 router + page shell
│       ├── index.css               Tailwind theme, typography, component classes
│       ├── types.ts                API response types
│       ├── vite-env.d.ts           Vite client types + typed env vars
│       ├── lib/
│       │   ├── api.ts              fetch client, configurable API base, error type
│       │   └── format.ts           number, date and percent formatting
│       ├── hooks/useApi.ts         abortable request hook with loading/error state
│       ├── context/CutoffContext.tsx   cutoff policy shared by every page
│       ├── components/
│       │   ├── Layout.tsx          sidebar, navigation, evaluation-period badge
│       │   ├── Controls.tsx        cutoff selectors + CSV export button
│       │   ├── KpiCard.tsx         metric card with definition tooltip
│       │   └── States.tsx          loading, empty and error states
│       ├── pages/
│       │   ├── Overview.tsx        headline KPIs, coverage, daily series
│       │   ├── Explorer.tsx        48 intervals for a delivery date
│       │   ├── Accuracy.tsx        daily table, distributions, worst intervals
│       │   ├── Methodology.tsx     policy, provenance, import history
│       │   └── About.tsx           author and project context
│       └── test/                   25 tests across 4 files
│           ├── setup.ts            jest-dom + fetch stubs
│           ├── fixtures.ts         deterministic API fixtures
│           ├── api.test.ts         URL building, error mapping
│           ├── Overview.test.tsx   KPIs, empty and error states
│           ├── Explorer.test.tsx   intervals, sorting, cutoffs, edge dates
│           └── App.test.tsx        shell and navigation
```

### 7.2 What each top-level item is for

| Path | Kind | Purpose |
| --- | --- | --- |
| `backend/` | Python service | FastAPI API, durable storage, import CLI, analytics |
| `backend/app/analysis/` | domain logic | cutoff selection, matching, metrics — no HTTP knowledge |
| `backend/app/db/` | persistence | schema, sessions, repository, migrations |
| `backend/app/elexon/` | integration | BMRS client, bounded windows, retries, normalisation |
| `backend/data/snapshots/` | committed data | real Elexon records used to seed an empty database offline |
| `backend/tests/` | tests | 102 backend tests, upstream mocked, no network required |
| `frontend/` | React app | dashboards, explorer, accuracy, methodology, CSV export |
| `docker-compose.yml` | infrastructure | one-command local/production-shaped stack |
| `render.yaml` | deployment | Render blueprint for the API and managed PostgreSQL |
| `frontend/vercel.json` | deployment | Vercel build, SPA rewrites, security headers |
| `.env.example` | configuration | every variable documented, placeholders only |
| `README.md` | documentation | product, methodology, setup, deployment, troubleshooting |

Generated or ignored at runtime (never committed): `backend/data/windsight.db*`,
`backend/data/cache/`, `frontend/node_modules/`, `frontend/dist/`, `.env`.

---

## 8. Prerequisites

| Tool | Requirement | Checked with |
| --- | --- | --- |
| Python | 3.11+ | 3.11.9 |
| Node.js | 20+ (22 recommended) | 22.x |
| npm | ships with Node | 10.x |
| Docker | Engine 24+ with Compose v2 | Docker 29.7.2, Compose v5.4.0 |
| Database | none locally (SQLite); PostgreSQL 14+ in production | — |

No Elexon API key is required.

---

## 9. Run with Docker (recommended)

```bash
cp .env.example .env          # optional: only to override defaults
docker compose up -d --build
docker compose ps             # both services must report (healthy)
```

- Frontend: <http://localhost:3000>
- Backend API docs: <http://localhost:8000/docs>
- Health: <http://localhost:3000/api/health>

The backend container runs, in order: Alembic `upgrade head` → seed from the committed
snapshot if the database is empty → warm the analytics cache. `/api/health` returns
`200` only when schema **and** data are ready, and the frontend waits on that health
check instead of guessing.

Stop without losing data:

```bash
docker compose down          # keeps the windsight-data volume
```

Remove everything, including imported history:

```bash
docker compose down -v       # destructive: deletes the database volume
```

### Verified Docker checks

| Check | Result |
| --- | --- |
| Image builds (backend, frontend) | pass |
| Both containers report `healthy` | pass |
| Fresh volume seeds itself from snapshot | pass (import run #2, 1,488 actual / 35,624 forecast) |
| Metrics via nginx at `:3000/api/overview` | 1,488 intervals, MAE 2,020.6 MW |
| `docker compose restart backend` | data intact |
| `docker compose down` + `up -d` | data intact (import run #2 still current) |
| Re-run import in container | `FUELHH inserted=0`, `WINDFOR inserted=0` — no duplicates |
| SPA deep links (`/accuracy`, `/methodology`) | 200 via nginx |
| Container users | backend `app`, frontend `nginx` (non-root) |

---

## 10. Run locally without Docker

### 10.1 Backend

```bash
cd backend
python -m venv .venv
# Windows (Git Bash):
source .venv/Scripts/activate
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

Configure (all optional locally — defaults point at `backend/data/windsight.db`):

```bash
cp ../.env.example .env       # then edit; `.env` itself is git-ignored
# DATABASE_URL=sqlite:///data/windsight.db
```

Create the schema and import real data:

```bash
# schema only (equivalent to: alembic upgrade head)
python -m app.scripts.import_historical_data --status --upgrade-schema

# import January 2026 from the live Elexon API
python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31

# or seed offline from the committed real snapshots
python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31 --source snapshot

# inspect what is stored (counts, publication range, coverage, recent runs)
python -m app.scripts.import_historical_data --status
```

Start the API:

```bash
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/api/health
```

### 10.2 Frontend

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173  (Vite proxies /api → http://localhost:8000)
```

`VITE_BACKEND_PROXY` overrides the proxy target if the API runs elsewhere.

### 10.3 Scripts

| Command | Effect |
| --- | --- |
| `npm run dev` | Vite dev server on 5173 |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest suite (25 tests) |
| `npm run build` | typecheck + production bundle into `dist/` |
| `npm run preview` | serve the built bundle |

---

## 11. Database, schema and migrations

Alembic is the single source of schema truth. Startup and the CLI apply
`upgrade head`; nothing calls `create_all`, so the schema cannot drift from the
migration history. No startup path drops tables.

### 11.1 Tables

**`actual_generation`** — FUELHH observations
`id`, `dataset`, `start_time` (tz-aware), `generation_mw`, `publish_time`, `settlement_date`,
`settlement_period`, `retrieved_at`
Unique: `(dataset, start_time)`

**`wind_forecasts`** — WINDFOR publications (every version retained)
`id`, `dataset`, `start_time`, `publish_time`, `generation_mw`, `retrieved_at`
Unique: `(dataset, start_time, publish_time)`

**`data_import_runs`** — audit trail, one row per dataset per attempt
`id`, `dataset`, `source`, `range_kind`, `range_start`, `range_end`, `started_at`,
`finished_at`, `status` (`running` | `completed` | `partial` | `failed`),
`records_retrieved`, `records_inserted`, `records_updated`, `records_skipped`,
`windows_total`, `windows_ok`, `windows_failed_json`, `error_detail`,
`coverage_verified`, `coverage_detail`

There is deliberately no `application_settings` table: configuration lives in the
environment, and no credentials are ever stored in the database.

### 11.2 Migrations

```bash
cd backend

# apply everything (uses DATABASE_URL, or the local SQLite default)
alembic upgrade head

# show the current revision
alembic current

# create a new revision after changing app/db/models.py
alembic revision --autogenerate -m "describe change"
```

The initial revision is `backend/alembic/versions/0001_initial_schema.py`.

### 11.3 Same schema, two engines

| Environment | Engine | Configuration |
| --- | --- | --- |
| Local / Docker | SQLite file **on a named volume** (`/app/data/windsight.db`) | `DATABASE_URL=sqlite:////app/data/windsight.db` |
| Production | Managed PostgreSQL (Render / Supabase / Neon / Heroku) | `DATABASE_URL=postgresql://…` |

`postgres://` and `postgresql://` provider URLs are normalised to the installed
`psycopg` 3 driver. **With `ENVIRONMENT=production` and no `DATABASE_URL`, startup fails
loudly instead of writing to a throwaway local file.**

---

## 12. Historical import: behaviour and guarantees

```bash
python -m app.scripts.import_historical_data \
  --from 2026-01-01 --to 2026-01-31 [--source live|snapshot] \
  [--upgrade-schema] [--database-url URL] [--status]
```

| Guarantee | How |
| --- | --- |
| Idempotent | Unique constraints + upserts on verified source identity; re-running inserts `0` |
| Correctable | A changed WINDFOR value for an existing `(start_time, publish_time)` updates in place; distinct publication versions are separate rows and never merged |
| Transactional | Each dataset batch commits atomically; a failure rolls back and is recorded |
| Honest status | `completed` only when requested windows succeeded **and** coverage was verified; otherwise `partial` / `failed` with details |
| Bounded retrieval | Requests split into windows (`ELEXON_WINDOW_DAYS`, default 15); failed windows are retried and reported |
| Forecast history | Publication range starts `FORECAST_HISTORY_DAYS` (30) before the delivery range so early-January delivery dates have eligible forecasts |
| No fabrication | A failed window produces no rows; the CLI exits non-zero |
| Concurrency | A refresh already running is rejected (`409`) instead of racing |

Statuses you will see: `completed`, `partial` (some windows or coverage missing),
`failed` (nothing usable written), `running` (in flight or crashed — safe to retry).

---

## 13. Verify persistence yourself

```bash
# 1. note the counts
docker compose exec backend python -m app.scripts.import_historical_data --status

# 2. restart the API container
docker compose restart backend
docker compose ps

# 3. the same counts must still be there
docker compose exec backend python -m app.scripts.import_historical_data --status

# 4. recreate the containers (volume survives)
docker compose down && docker compose up -d
curl -s http://localhost:3000/api/health | python -m json.tool | head -20
```

Expected: `actual_records: 1488`, `forecast_records: 35624`, and the same latest import
run id after each step. Without Docker, restart `uvicorn` and the counts are unchanged
because they live in `backend/data/windsight.db`.

---

## 14. Tests

### Backend — 102 passed

```bash
cd backend && python -m pytest
```

Covers: live-API client behaviour, windowing/retries, normalisation and validation,
cutoff selection, forecast/actual matching, MAE/RMSE/bias/MAPE, CSV export, error
handling, persistence (import, re-import without duplicates, retry after failure,
partial coverage, transaction rollback, publication timestamps preserved, analytics
from the database, cache invalidation, unavailable database, empty database,
protected refresh). Elexon is mocked — the suite needs no network.

### Frontend — 25 passed (4 files)

```bash
cd frontend && npm test        # vitest
npm run typecheck              # tsc --noEmit
npm run build                  # production bundle
```

Result: `Test Files 4 passed`, `Tests 25 passed`; typecheck clean; build succeeds
(648 kB JS, 25 kB CSS; the 500 kB chunk warning is expected for the charting bundle).

---

## 15. Configuration reference

| Variable | Default | Required | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | SQLite `data/windsight.db` (dev) | **yes in production** | `sqlite:////app/data/windsight.db` in Docker; `postgresql://…` in production |
| `ENVIRONMENT` | `development` | production only | `production` forbids the SQLite fallback |
| `SEED_ON_STARTUP` | `true` | no | seed from snapshot only when the DB is empty |
| `ADMIN_TOKEN` | empty | no | enables `POST /api/refresh`; empty = endpoint disabled (403) |
| `ELEXON_BASE_URL` | `https://data.elexon.co.uk/bmrs/api/v1` | no | |
| `EVAL_START` / `EVAL_END` | `2026-01-01` / `2026-01-31` | no | delivery-date range |
| `DECISION_CUTOFF_HOUR` / `_MINUTE` | `12` / `0` | no | Europe/London |
| `DECISION_CUTOFF_DAY_OFFSET` | `-1` | no | `-1` = day before delivery |
| `FORECAST_HISTORY_DAYS` | `30` | no | extra publication history before the period |
| `ENABLE_LIVE_FETCH` | `true` | no | `false` = stored data only |
| `ALLOW_SNAPSHOT_FALLBACK` | `true` | no | seed/read snapshot when upstream is down (always labelled) |
| `ELEXON_WINDOW_DAYS` | `15` | no | max days per upstream request |
| `ELEXON_TIMEOUT_SECONDS` / `_MAX_RETRIES` / `_BACKOFF_SECONDS` | `60` / `3` / `1.5` | no | |
| `CACHE_TTL_SECONDS` | `86400` | no | upstream response cache |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000,http://localhost:8000` | production: set to the frontend origin | comma-separated |
| `AUTH_ENABLED` | `false` | no | read-only demo has no user auth |
| `VITE_API_BASE_URL` | empty | production split-origin | build-time; absolute backend origin |
| `VITE_BACKEND_PROXY` | `http://localhost:8000` | no | dev-server proxy target |

Secrets belong in the host's environment settings (Render/Vercel/Heroku dashboards),
never in the repository. `.env` is git-ignored; `.env.example` holds placeholders only.

---

## 16. Deployment

### 16.1 Status of this repository

**No production deployment has been executed from this workspace.** There are no Vercel,
Render, Railway, Fly, Heroku or database credentials in the environment, and no git
remote exists yet. Everything below is the exact, verified-in-local-equivalent procedure;
nothing in it has been falsely marked as done.

Deployment URLs live in **section 1**: replace `__PASTE_VERCEL_URL_HERE__` and
`__PASTE_API_URL_HERE__` once both hosts are live. Do not paste a URL before it has
answered a request.

The local stack *was* run in the production shape: the built frontend served by
unprivileged nginx, a second origin for the API, and CORS restricted to that origin —
`Origin: http://localhost:4178` → `access-control-allow-origin: http://localhost:4178`,
dashboard loaded from a cross-origin API. That is the same code path used on Vercel +
Render.

### 16.2 Target architecture

| Component | Host | Why |
| --- | --- | --- |
| Frontend (static) | **Vercel** | assignment requirement; free tier, SPA rewrites included |
| Backend (Docker) | **Render** | repository `render.yaml` blueprint, Docker support, free TLS |
| Database | **Render managed PostgreSQL** | durable across deploys; volumes are not usable for free web services |

Vercel cannot host this Python backend itself (no long-running Docker/Python server on
the plan used here), so the API lives on Render and the frontend points at it with
`VITE_API_BASE_URL`. Same-origin nginx proxying remains the default for Docker/local.

### 16.3 Step 1 — publish the repository

```bash
cd <repo>
git add -A
git commit -m "WindSight: durable Elexon history, analytics API, React UI, Docker stack"
gh repo create <anonymous-name> --public --source=. --remote=origin --push
# or: git remote add origin <url> && git push -u origin main
```

Check before pushing: `.env` must not be tracked (`git check-ignore -v .env`), and
`backend/data/windsight.db` must not be committed (it is git-ignored; the committed
snapshots under `backend/data/snapshots/` are the seed source).

### 16.4 Step 2 — backend + database on Render

1. Render dashboard → **New → Blueprint** → select the repository. `render.yaml`
   provisions `windsight-db` (PostgreSQL) and `windsight-api` (Docker, `backend/`,
   health check `/api/health`).
2. When prompted for `CORS_ORIGINS`, enter the Vercel origin (add it after step 3 if
   you do not have it yet — it can be edited later).
3. `ADMIN_TOKEN` is auto-generated. Keep the refresh endpoint disabled if you prefer:
   delete the variable.
4. Wait for the deploy. Startup applies Alembic migrations, then seeds from the
   committed snapshot only if the database is empty.

Verify:

```bash
curl -s https://<service>.onrender.com/api/health | jq '.status, .data.origin, .database.database_kind'
# expect: "ready", "database", "postgresql"
```

### 16.5 Step 3 — frontend on Vercel

1. Vercel → **Add New → Project** → import the same repository.
2. **Root Directory:** `frontend`. Framework preset: Vite (auto-detected).
3. Environment variable (Production **and** Preview):
   `VITE_API_BASE_URL=https://<service>.onrender.com`
4. Deploy. `frontend/vercel.json` supplies the build command, SPA rewrites and security
   headers, so `/accuracy` and `/methodology` survive a page refresh.
5. Copy the deployed origin and set it on Render as
   `CORS_ORIGINS=https://<project>.vercel.app`, then redeploy the API (or restart it).

Verify:

```bash
curl -s https://<project>.vercel.app/ | head -5          # HTML shell
curl -sI https://<project>.vercel.app/accuracy | head -1 # 200, SPA fallback
```

### 16.6 Step 4 — import production data (deliberate, one-off)

Production and local databases are separate. Import into production explicitly:

```bash
# Render dashboard → windsight-api → Shell
python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31
python -m app.scripts.import_historical_data --status
```

`DATABASE_URL` is already injected, so no URL needs typing. Expected output:
`actual=1488`, `forecast=35624`, `coverage_verified=True`, `1488/1488` intervals.

Redeploy the service and re-check `/api/health` — the counts must persist. This is the
production equivalent of the local restart test in section 13.

### 16.7 Step 5 — production verification checklist

| Check | Command / action | Expected |
| --- | --- | --- |
| Health | `GET /api/health` | `200`, `"origin": "database"`, `database_kind: postgresql` |
| Schema | `alembic current` in Shell | `0001_initial_schema (head)` |
| Analytics | open `/` | MAE, RMSE, bias, MAPE with 1,488 intervals |
| Explorer | `/explorer`, date `2026-01-15` | 48 intervals, publication ≤ 14 Jan 12:00 UTC |
| Cutoff switch | change 12:00 → 09:30 | metrics change (MAE 2,020.6 → 2,126.1 MW locally) |
| Accuracy | `/accuracy` | 31 daily rows, warnings, export link |
| CSV | click **Export CSV** | 1,488 rows + header, `attachment; filename=…csv` |
| Refresh guard | `curl -X POST .../api/refresh` | `403 refresh_disabled` unless `ADMIN_TOKEN` is set |
| Persistence | redeploy API, re-check health | same counts |
| Logs | Render logs | no tracebacks, no credential values |

### 16.8 Alternative: Heroku backend

`backend/Procfile` is already present.

```bash
heroku create <name>
heroku addons:create heroku-postgresql:essential-0 -a <name>   # sets DATABASE_URL
heroku config:set ENVIRONMENT=production CORS_ORIGINS=https://<vercel-domain> -a <name>
heroku stack:set container -a <name>        # or use the Python buildpack
git subtree push --prefix backend heroku main
heroku run python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31 -a <name>
```

Heroku rewrites `postgres://` URLs; the application normalises the scheme to `psycopg`
automatically. The filesystem is ephemeral — Postgres is mandatory there.

### 16.9 Why not SQLite in production

SQLite on a container volume is correct for the single-instance Docker demo (verified),
but hosted platforms either lack persistent disks or lose them on redeploy/scale-out.
Production therefore uses managed PostgreSQL with the same Alembic migrations and the
same import command. The application refuses to start in `ENVIRONMENT=production`
without `DATABASE_URL`.

---

## 17. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `sqlalchemy.exc.OperationalError: connection refused` | Postgres unreachable | check `DATABASE_URL`, database status, provider firewall; `/api/health` shows `reachable: false` |
| Startup: `DATABASE_URL is not set` | production env without a database | set `DATABASE_URL`, or unset `ENVIRONMENT=production` for local work |
| `503 no_data` / dashboard shows "no imported history" | database empty | run the import CLI (section 12), then reload |
| `503 data_unavailable` on every page | DB reachable but tables empty, or import incomplete | `--status`, then re-run the import |
| `port 8000 already in use` | another uvicorn/Docker instance | stop it, or run `--port 8010` (and set `VITE_BACKEND_PROXY`) |
| `port 3000/5173 already in use` | other dev servers | `npm run dev -- --port 5174`; Compose: edit the published port |
| Docker service never becomes healthy | backend still seeding, or DB error | `docker compose logs backend`; health must return 200 |
| Frontend loads but every panel errors | API down or wrong origin | check `VITE_API_BASE_URL`, `/api/health`, browser console network tab |
| CORS error in production | `CORS_ORIGINS` missing the Vercel origin | add it and restart the API; preview and production origins both need entries |
| `alembic.util.exc.CommandError` | wrong working directory or missing `DATABASE_URL` | run from `backend/`; confirm `alembic current` |
| Import says `partial` | a window failed or coverage has gaps | read `windows_failed` in `--status`; re-run — it is safe and idempotent |
| Import exits 1 with `403`/network error | Elexon unavailable/rate-limited | retry later, or import `--source snapshot` for the committed real data |
| Data gone after deploy | platform has an ephemeral filesystem | use managed PostgreSQL; never rely on container-local SQLite |
| Empty dashboard after deploy but health is ready | frontend built without `VITE_API_BASE_URL` | set it in Vercel and redeploy (build-time variable) |
| `bind: address already in use` in Compose | host port taken | change `"8000:8000"` / `"3000:8080"` |

---

## 18. Security and operational notes

- No secrets in the repository; `.env` is git-ignored, `.env.example` is placeholder-only.
- Public API is **read-only** except `POST /api/refresh`, which is disabled unless
  `ADMIN_TOKEN` is set and then requires `X-Admin-Token` (constant-time comparison).
- No endpoint exposes arbitrary SQL or the database connection string; `/api/health`
  redacts credentials (`user:***@host`).
- Date ranges, cutoff times and offsets are validated; bad input returns a structured
  `400`, never a traceback.
- CORS is an explicit allow-list; production should contain only the deployed origin.
- Container images run as non-root (`app`, `nginx`) and carry no secrets.
- Startup is non-destructive: `upgrade head` only, never a drop/create.
- Analytics results are cacheable; `/api/health` is `no-store`.
- Logs contain counts, durations and error classes — never credentials or tokens.

---

## 19. Known limitations

1. **Decision cutoff is an assumption.** The real GB day-ahead gate closure is not
   modelled beyond this configurable policy.
2. **Forecast vintage granularity.** WINDFOR publishes in half-hourly batches; only
   publications present in the source are eligible, so a missing earlier vintage falls
   back to the next-latest eligible one.
3. **FUELHH settlement mapping.** `settlement_period` is retained for reference but not
   used analytically; intervals are keyed by UTC `startTime`.
4. **MAPE** is reported only over non-zero actuals, with the excluded count shown.
5. **No authentication** for end users — the demo is read-only by design.
6. **No scheduled refresh.** Import is a deliberate CLI/operator action; no background
   scheduler exists (intentional for this assignment's 16-hour budget).
7. **Bundle size**: the charting bundle is 648 kB minified (183 kB gzipped). Code
   splitting was not worth the complexity here.
8. **Deployment not executed** from this environment (no credentials); the procedure in
   section 16 is the verified local equivalent plus host-specific steps.
9. **Render free tier** sleeps after inactivity (cold start ~50 s) and its free Postgres
   instance is time-limited; use paid plans for a durable demo.

---

## 20. AI disclosure

This project was built with an AI coding agent (Codebuff / Freebuff) used for
scaffolding, implementation assistance, test authoring and documentation. All data is
real Elexon data fetched from the public API; no synthetic observations are included.
All numbers in this README were produced by running the code in this repository, and
statements about tests and deployment reflect what was actually executed.

---

## 21. Demonstration guide (business audience)

1. **Overview** — point at the evaluation period, 1,488 matched intervals, MAE 2,021 MW.
2. **Bias** — +1,806 MW: the day-ahead forecast systematically overestimated January
   2026 wind; the narrative explains why bias alone is not accuracy.
3. **Explorer, 15 Jan 2026** — selected publication 14 Jan 11:30 UTC; show a large
   interval and the signed error.
4. **Cutoff 12:00 → 09:30** — metrics change, because a different forecast vintage was
   eligible. This is the core product principle.
5. **Accuracy** — daily variation; note the worst days.
6. **Export CSV** — the same selection, with publication provenance, for downstream work.
7. **Methodology** — cutoff, provenance, import history and limitations, so the numbers
   are auditable.

## 22. Technical review guide

| Decision | Rationale |
| --- | --- |
| Separate domain/business layer (`analysis/`) from transport (`api/`) | selection latency can be tested without HTTP |
| Cutoff applied before matching, per interval | prevents look-ahead leakage, the central correctness risk |
| Durable observations, metrics computed on read | cutoff/range changes stay correct; no stale precomputed KPIs |
| Alembic-only schema, no `create_all` | reproducible environments, no drift |
| Import runs as first-class records with explicit statuses | an HTTP 200 is never confused with complete coverage |
| Unique `(dataset, start_time, publish_time)` | corrects values without merging forecast vintages |
| ~100 focused backend tests with mocked upstream | deterministic suite, no network dependency |
| Two storage targets, one schema | SQLite for the demo, Postgres for production, identical code path |

---

*Author: Raushik. Data: Elexon BMRS (FUELHH, WINDFOR), open licence.*
