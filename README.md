# Fleet Optimization Platform

A full-stack platform for fleet trip planning and optimization. Three independently deployable parts — `frontend`, `backend`, `ml` — that work together over HTTP.

- **frontend/** — React + TypeScript + Vite, TailwindCSS, React Query, React Router, Recharts, Leaflet.
- **backend/** — FastAPI + SQLAlchemy + Alembic, backed by PostgreSQL (hosted on [Supabase](https://supabase.com)).
- **ml/** — Standalone Python service (scikit-learn/XGBoost + a DSA/ML-hybrid route optimizer) exposing `/predict/*` and `/optimize/*` endpoints, called by the backend over HTTP so it can scale/deploy separately.

The **Trip module** is the first fully-built vertical slice: trip CRUD, a trip list page, and a 5-tab trip detail page (Route Intelligence, Vehicle Intelligence, Driver Intelligence, Real-Time Operations, Reporting & KPI). Vehicles and Drivers reuse the same backend models/tables; their own dedicated frontend pages come later — today they're exposed via the roster endpoints used when assigning a route.

## What's built

- **Trips** — CRUD, filterable/searchable list, lazy status auto-transition (`scheduled → in-transit → Delivered/Delayed`).
- **Routes** — group multiple existing trips into one dispatched run (`CreateRouteModal`: pick trips → driver → vehicle → per-trip load → review), with the stop order optimizable via `POST /api/routes/optimize` — an exact Held-Karp TSP solver for small stop counts, falling back to a nearest-neighbor + 2-opt heuristic, or the ML service's hybrid solver (`ml/src/optimizer`) when ML-ranked candidates are available. Route stops can also be reordered manually and re-optimized after assignment.
- **Route Intelligence** — weather-adjusted ETA per stop (OSRM + OpenWeather + a rule-based delay multiplier table), computed fresh on every read rather than stored.
- **Vehicle & Driver Intelligence** — per-trip tabs backed by `vehicle_intelligence_service.py` / `driver_intelligence_service.py`, plus roster endpoints (`/api/roster/drivers`, `/api/roster/vehicles`) that flag drivers/vehicles already on a trip.
- **Real-Time Operations** — GPS breadcrumb history and live position per trip (`/api/trips/{id}/breadcrumbs`, `/api/trips/{id}/live`).
- **Reporting & KPI** — fleet-wide KPI summary/detail (`/api/trips/kpi-summary`, `/api/trips/kpi-detail`).
- **ML predictions** — delay risk, expected delay (minutes), fuel-liters, and trip-cost, all XGBoost/scikit-learn models served by the standalone `ml` service and persisted per-trip via `/api/predictions/*`.

## Database

This project uses [Supabase](https://supabase.com) (hosted Postgres) instead of a local Postgres container. Create a Supabase project, grab the connection string from **Project Settings > Database > Connection string (URI)**, and put it in `backend/.env` as `DATABASE_URL` (see `backend/.env.example` for the exact format — note the `postgresql+psycopg2://` scheme and `?sslmode=require`).

## Run everything with Docker

```bash
cp backend/.env.example backend/.env   # fill in your Supabase DATABASE_URL
docker-compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (docs at /docs, health at /health)
- ML service: http://localhost:8001 (health at /health)

## Run each part locally (without Docker)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # fill in your Supabase DATABASE_URL
alembic upgrade head    # once migrations exist
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

### ML service

```bash
cd ml
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/train.py --model eta --input data/raw/trips.csv   # train the example ETA model
python src/optimizer/train_ml.py                             # optional: train the hybrid solver's ranking models
uvicorn service.ml_api:app --reload --port 8001
```

Prediction request shapes are defined inline in `ml/service/ml_api.py` and must be kept in sync with
`ml/feature_contract_v2.json` (delay/expected-delay) and `ml/src/features/build_features.py`
(fuel/trip-cost) — see the comments on each Pydantic model in `ml_api.py` for which contract governs
which endpoint.

## Where to add new features

| Adding...                                   | Goes in...                                                        |
|----------------------------------------------|---------------------------------------------------------------------|
| A new API resource (CRUD)                     | `backend/app/models/`, `schemas/`, `services/`, `api/routes/`      |
| A new DB table/column                         | `backend/app/models/` + `alembic revision --autogenerate`          |
| New frontend page                             | `frontend/src/pages/` + register the route in `App.tsx`            |
| New Trip-detail tab or trip-specific widget   | `frontend/src/components/trip/`                                     |
| Reusable UI (buttons, tables, modals)         | `frontend/src/components/common/`                                   |
| New API call from the frontend                | `frontend/src/api/` + a hook in `frontend/src/hooks/`               |
| A new ML model                                | `ml/src/models/` (train/predict), wire into `ml/src/train.py`, add an endpoint in `ml/service/ml_api.py` |
| Route optimizer / TSP logic                   | `ml/src/optimizer/` (DSA + ML-hybrid solver), `backend/app/services/route_optimizer.py` (exact/heuristic solver called directly from the backend) |
| Backend calling a new ML endpoint             | `backend/app/services/ml_client.py`                                 |
| Roster / assignment logic (driver, vehicle availability) | `backend/app/services/roster_service.py`, `backend/app/api/routes/roster.py` |

## Conventions

- IDs are named consistently with the schema: `trip_id`, `driver_id`, `vehicle_id`, `route_id`, `stop_id`.
- All URLs, DB credentials, and API keys come from environment variables — see `.env.example` in `frontend/` and `backend/`. Never commit real `.env` files.
- The backend never imports ML code directly — it always calls the `ml` service over HTTP, so ML can be scaled or redeployed independently.

## Further reading

- [README2.md](./README2.md) — deep-dive walkthrough of the trip → route → route-optimization → weather-adjusted-ETA slice, with sequence diagrams and known gotchas (predates the current multi-trip `assign`-based route flow in places, but the architecture/status-lifecycle sections still hold).
- [WEIGHT_AWARE_ROUTING.md](./WEIGHT_AWARE_ROUTING.md) — architecture of the route optimizer's implemented multi-objective cost model (distance/time/fuel/cargo, baseline-normalized) and the 5-step Create Route wizard.
- [MULTI_VEHICLE_ROUTING.md](./MULTI_VEHICLE_ROUTING.md) — multi-vehicle fleet routing: the solver and API are built (`POST /api/routes/optimize-fleet`); hub coordinates and the frontend are not. Includes an explicit list of what is and isn't modeled.

## One-off scripts

- `backend/backfill_planned_distance_km.py` — recomputes `planned_distance_km` (via OSRM) for any trip that has GPS coordinates but a null distance, so ML predictions that depend on it (delay, expected-delay, fuel-cost) stop failing for those trips. Run once from `backend/` with its venv active: `python backfill_planned_distance_km.py`.
