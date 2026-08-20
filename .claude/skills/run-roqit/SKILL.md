---
name: run-roqit
description: Build, run, and drive the roqit_new fleet-optimization platform (FastAPI backend, FastAPI ml service, React/Vite frontend). Use when asked to start the app, run the backend/ml/frontend, take a screenshot of the Trips UI, hit an API endpoint, or verify a change actually works end-to-end.
---

Three services, three separate binaries sharing one skill: **backend** (FastAPI, port 8000),
**ml** (FastAPI, port 8001), **frontend** (React/Vite, port 5173). Backend and ml are driven with
`curl`; the frontend is driven with `.claude/skills/run-roqit/driver.mjs`, a small
chromium-cli-style Playwright wrapper (`chromium-cli` itself isn't installed in this environment).

All paths below are relative to the repo root (`roqit_new/`).

## Prerequisites

- Python 3.14 and Node 24+ (whatever's on `PATH` — verified with these exact versions).
- A Supabase Postgres connection string for `backend/.env` (`DATABASE_URL`). Without a real one,
  the backend starts but every DB-backed endpoint fails.
- Internet access once, to download Playwright's Chromium (~200 MB) for the frontend driver.

```powershell
python --version   # 3.14.5 in this environment
node --version     # v24.16.0
```

## Setup

### Backend

```powershell
cd backend
python -m venv .venv
copy .env.example .env   # then fill in DATABASE_URL (Supabase) — see backend/.env.example
```

`requirements.txt` pins versions that predate Python 3.14 wheel availability — installing it
as-is fails partway through (see Gotchas). Install the compatible set instead:

```powershell
.\.venv\Scripts\python.exe -m pip install fastapi==0.115.6 "uvicorn[standard]==0.32.1" alembic sqlalchemy httpx python-dotenv
.\.venv\Scripts\python.exe -m pip install psycopg2-binary pydantic pydantic-settings --upgrade
```

(Exact working versions as of this writing: `psycopg2-binary` 2.9.12, `pydantic` 2.13.4,
`sqlalchemy` 2.0.52 — installing unpinned/latest resolved all three.)

### ML service

```powershell
cd ml
python -m venv .venv
```

Same Python-3.14-wheel problem, worse (scikit-learn/numpy/pandas need a C/Rust toolchain to
build from source, which isn't installed):

```powershell
.\.venv\Scripts\python.exe -m pip install fastapi==0.115.6 "uvicorn[standard]==0.32.1" httpx python-dotenv joblib==1.5.3
.\.venv\Scripts\python.exe -m pip install pydantic --upgrade
.\.venv\Scripts\python.exe -m pip install scikit-learn==1.9.0 xgboost==3.2.0 pandas==3.0.2 numpy==2.4.6
```

Model artifacts (`ml/models_store/*.pkl`) are already committed — no training step needed to run
the service. They load and predict correctly under these newer library versions (verified — see
Run section).

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env
```

### Driver (one-time)

```powershell
cd .claude\skills\run-roqit
npm install
npx playwright install chromium
```

## Run (agent path)

Start all three, each in the background, each logging to a file so you can inspect failures
without a blocking foreground process:

```powershell
# Backend — port 8000. No --reload: see Gotchas (orphaned worker processes).
Start-Process -FilePath "backend\.venv\Scripts\python.exe" `
  -ArgumentList "-m uvicorn app.main:app --port 8000" -WorkingDirectory backend `
  -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\roqit_backend.log" -RedirectStandardError "$env:TEMP\roqit_backend.err.log"

# ML — port 8001
Start-Process -FilePath "ml\.venv\Scripts\python.exe" `
  -ArgumentList "-m uvicorn service.ml_api:app --port 8001" -WorkingDirectory ml `
  -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\roqit_ml.log" -RedirectStandardError "$env:TEMP\roqit_ml.err.log"

# Frontend — port 5173
Start-Process -FilePath "cmd.exe" -ArgumentList "/d /s /c npm run dev" -WorkingDirectory frontend `
  -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\roqit_frontend.log" -RedirectStandardError "$env:TEMP\roqit_frontend.err.log"
```

Wait for readiness, then verify:

```powershell
Start-Sleep -Seconds 5
curl.exe -s -o NUL -w "backend: %{http_code}`n" http://localhost:8000/docs
curl.exe -s -o NUL -w "ml: %{http_code}`n"      http://localhost:8001/docs
curl.exe -s -o NUL -w "frontend: %{http_code}`n" http://localhost:5173/
```

### Backend / ML — drive with curl

```bash
curl http://localhost:8000/api/trips?limit=5
curl -X POST http://localhost:8001/predict/fuel-liters -H "Content-Type: application/json" -d '{
  "vehicle_type": "Truck", "road_type": "Highway", "traffic_density": "Medium",
  "weather_condition": "Clear", "fuel_type": "Diesel", "planned_distance_km": 500,
  "load_weight_kg": 8000, "avg_kmpl_rated": 8.5, "vehicle_age_years": 3, "fuel_price_per_l": 92.5
}'
# → {"predicted_fuel_liters":101.8577880859375}
```

### Frontend — drive with the Playwright driver

`driver.mjs` reads one command per line from a file or stdin and mirrors `chromium-cli`'s
vocabulary: `nav`, `wait-for`, `click`, `fill`, `press`, `screenshot`, `console-errors`. Full list
in the file's header comment.

```bash
cd .claude/skills/run-roqit
node driver.mjs <<'EOF'
nav http://localhost:5173
wait-for text=Trips
sleep 4000
screenshot trips-page
click text=Create Trip
wait-for text=Create trip
screenshot create-trip-modal
console-errors
EOF
```

Screenshots land in `.claude/skills/run-roqit/screenshots/`. A failing command auto-saves
`screenshots/failure.png` and exits non-zero, so a driver script's exit code is meaningful.

Verified this session: `trips-page.png` (sidebar, KPI header, Trips toolbar all render) and
`create-trip-modal.png` (clicking "Create Trip" opens the real 5-step wizard) — both with zero
console errors. See Gotchas for why the trips *table* itself may still say "Loading trips..." in
a screenshot even though the page and its interactions are genuinely working.

### Stop

```powershell
Get-NetTCPConnection -LocalPort 8000,8001 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Where-Object { $_.CommandLine -like "*vite*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## Run (human path)

```powershell
cd backend;  .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
cd ml;       .\.venv\Scripts\python.exe -m uvicorn service.ml_api:app --reload --port 8001
cd frontend; npm run dev
```

Each blocks its terminal; Ctrl-C to stop. `--reload` is fine here since a human is watching and
can Ctrl-C cleanly — the danger (below) is specifically about orphaned reload workers piling up
across many *agent-driven* restarts.

## Test

No automated test suite exists in this repo: `frontend/package.json` has no `test` script, and
there is no `test_*.py`/`conftest.py` anywhere under `backend/` or `ml/`. "Testing" this project
today means driving it live (above) or checking `/docs` renders and a real request round-trips.

---

## Gotchas

- **`requirements.txt` pins predate Python 3.14 wheels.** `psycopg2-binary==2.9.10`,
  `pydantic==2.10.3` (→ `pydantic-core`), and `sqlalchemy==2.0.36` all try to build from source on
  3.14 and fail — `psycopg2` needs `pg_config`, `pydantic-core` needs a Rust toolchain (`cargo`/
  `maturin`), neither is installed. Same story for `ml/requirements.txt`'s `scikit-learn==1.5.2`
  (needs a C/C++ compiler via meson). Installing the unpinned/latest versions of just those
  packages (exact versions in Setup) resolves it without touching anything else. The pickled
  model artifacts in `ml/models_store/` still load and predict correctly under the newer
  scikit-learn/xgboost/numpy/pandas — verified with a real `/predict/fuel-liters` call.

- **`uvicorn --reload` leaves orphaned worker processes on Windows.** The reloader
  (`Started reloader process [N]`) spawns a separate worker process via `multiprocessing`;
  `Stop-Process` on the reloader's PID does **not** kill that child. Across several restarts this
  leaves multiple stale processes all bound to the same port, so requests land on random ones —
  some serving old code, one of them possibly hung. Symptom: CORS/config changes you just made
  don't seem to take effect, or the same endpoint alternates between old and new behavior on
  successive requests. Fix: before restarting, find and kill *every* `python.exe` whose
  `CommandLine` matches `app.main:app` or `service.ml_api:app`
  (`Get-CimInstance Win32_Process -Filter "Name='python.exe'"`), not just the one PID you
  launched with. This is exactly why the agent-path Run command above omits `--reload` —
  simpler to just relaunch than to manage reload's process tree.

- **The Supabase DB is a live, shared, rate-limited resource — not a local throwaway.**
  `DATABASE_URL` points at Supabase's **session-mode pooler**, capped at 15 concurrent client
  connections total. Each `uvicorn` process holds its own SQLAlchemy pool (up to 15 connections by
  default: `pool_size=5` + `max_overflow=10`). A handful of backend restarts across a working
  session is enough to exhaust the shared cap before Supabase reclaims the old sessions — you'll
  see `sqlalchemy.exc.OperationalError: ... FATAL: (EMAXCONNSESSION) max clients reached in
  session mode - max clients are limited to pool_size: 15` in the backend log, and requests hang
  for 10-20s or 500. `GET /api/routes` makes this dramatically worse: it opens one DB session
  **per stored route** (fan-out via `asyncio.gather`) plus an OSRM + N-OpenWeather call per route,
  so on a dev DB that's accumulated many test routes (ours has hundreds), one call to
  `GET /api/routes` alone can hold the pool for a long time and starve every other endpoint on the
  same page load — including simple ones like `/api/trips`. This is *the* reason the Trips page
  can sit on "Loading trips..." even when the backend, frontend, and your code are all fine.
  There's no local fix beyond patience (wait ~30-60s and retry) or reducing concurrent DB-backed
  requests; see README2.md §7.2 for the underlying code-level cause and its fix.

- **That DB-exhaustion 500 sometimes reaches the browser without CORS headers**, so instead of a
  `500` you see `Access to XMLHttpRequest ... has been blocked by CORS policy: No
  'Access-Control-Allow-Origin' header is present` in the console, plus `net::ERR_FAILED` on the
  request. This looks exactly like a CORS *configuration* bug (and cost real time chasing it as
  one) but `BACKEND_CORS_ORIGINS` is correct — check the backend log for `EMAXCONNSESSION` first
  before touching CORS config.

- **Two known app bugs block a fully-clean `/api/routes` response**, both documented in
  `README2.md` §7.2/§7.3: a `TypeError: can't compare offset-naive and offset-aware datetimes` in
  `eta_service.py`, and a concurrency-unsafe shared DB session across `asyncio.gather` in
  `routes.py`. Both were patched locally in this working tree while building this skill (uncommitted
  — `git status` shows `backend/app/services/eta_service.py` and `backend/app/api/routes/routes.py`
  modified) to get a clean end-to-end run. If those files are back to their original state, expect
  `/api/routes` (and anything that calls it, like the Trips-detail Route Intelligence tab) to 500
  or hang; README2.md §7 has the exact fix.

- **Nominatim (geocoding) 403s under shared/heavy usage.** `POST /api/geocode` proxies to the
  free public Nominatim instance, which rate/IP-limits aggressively. A `502` from that endpoint
  usually means Nominatim itself returned `403 Forbidden`, not a bug here.

## Troubleshooting

- **`ERROR: Failed building wheel for psycopg2-binary` / `pydantic-core` / `scikit-learn`**: pinned
  version has no Python 3.14 wheel and no local build toolchain. Install the unpinned/latest
  version of just that package instead (see Setup).
- **Backend log shows `EMAXCONNSESSION`, or requests hang 10-20s then 500/timeout**: Supabase
  connection pool exhausted — see Gotchas. Wait and retry; don't restart the backend repeatedly,
  that makes it worse.
- **Browser console shows a CORS error but `BACKEND_CORS_ORIGINS` already matches the frontend
  origin**: it's very likely the DB-exhaustion 500 above, not CORS. Check the backend log.
- **`net::ERR_ADDRESS_IN_USE` / port already bound when relaunching**: an orphaned `--reload`
  worker (see Gotchas) — enumerate `python.exe`/`node.exe` processes by `CommandLine` and kill
  all matches, not just the last PID you started.
- **Frontend shows a blank "Loading X..." forever with no console errors at all**: the request is
  still in flight (not failed) — almost always the Supabase pool contention above. Give it real
  time (30-60s) before assuming something's broken.
