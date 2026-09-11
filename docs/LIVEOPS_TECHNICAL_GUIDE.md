# Roqit LiveOps Platform — Technical Guide

> **Audience:** Engineering teams, architects, and technically-inclined reviewers.
> **Companion document:** `LIVEOPS_EXECUTIVE_OVERVIEW.md` (for business stakeholders).

---

## 1. System Overview

LiveOps is the real-time dispatch and monitoring core of the Roqit fleet platform. It comprises **three deployable services** plus supporting infrastructure:

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│  Frontend (React 18 + TS)   │  HTTP  │  Backend API (FastAPI, Python)   │
│  - LiveOps page             │◄──────►│  - REST API (/api/*)             │
│  - Live map (Leaflet)       │  SSE   │  - SSE realtime stream (/events) │
│  - TanStack Query polling   │        │  - Worker supervisor (threads)   │
└─────────────────────────────┘        │    ├ trip-assignment worker      │
                                       │    ├ lns-worker (manual trigger) │
                                       │    ├ trip-completion worker      │
                                       │    └ unassigned-trips sweeper    │
                                       └───────┬──────────────┬───────────┘
                                               │ HTTP         │ SQLAlchemy
                                               ▼              ▼
                                    ┌────────────────────┐  ┌──────────┐
                                    │  ML Service (Fast) │  │ Postgres │
                                    │  - XGBoost models  │  │   (DB)   │
                                    │  - OR-Tools solver │  └──────────┘
                                    └────────────────────┘
                                               ▲
                     ┌─────────────────────────┼──────────────────────┐
                     │                         │                      │
              OSRM (routing)           Weather API            Geocoding API
```

### Design principles
- **Single-process workers:** the FastAPI lifespan hook starts daemon threads inside the API process (single-producer/single-consumer scale; simple ops, no separate broker needed for the demo scale).
- **Async by default:** `async` endpoints for I/O-bound work; a custom in-process `Queue`/`Worker` infrastructure for background jobs.
- **Distributed safety:** Redis-backed **locks** guard LNS runs and route mutations; **optimistic versioning** (`Route.version`) guards concurrent plan edits.
- **Explainability:** every optimization decision is written to an `OptimizationAudit` record with before/after route snapshots and cost deltas.
- **Human-in-the-loop:** periodic LNS is intentionally **disabled**; heavy re-optimization is triggered manually via `POST /api/routes/lns/trigger`.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, TanStack Query (polling), Leaflet (map), Tailwind CSS, SSE client (`EventSource`) |
| Backend | Python 3.x, FastAPI, Uvicorn, SQLAlchemy (ORM), Pydantic |
| ML Service | FastAPI, XGBoost (trained `.pkl` models in `models_store/`), NumPy, scikit-learn, Google **OR-Tools** (routing solver) |
| Database | PostgreSQL (via SQLAlchemy models; CRUD through FastAPI dependencies) |
| Routing/Distance | **OSRM** (table/route services) via `osrm_client.py` |
| External data | Weather API (`weather_client.py`), Geocoding API (`geocode_client.py`) |
| Deployment | `docker-compose.yml` orchestrating frontend, backend, ml, postgres, osrm |

Key backend dependencies (`backend/requirements.txt`): fastapi, uvicorn, sqlalchemy, psycopg2, httpx, redis, pydantic.
Key ML dependencies (`ml/requirements.txt`): fastapi, uvicorn, xgboost, scikit-learn, ortools, numpy, pandas, joblib.

## 3. Repository Layout

```
Roqit-Demo/
├── backend/                      # FastAPI application
│   └── app/
│       ├── main.py               # App factory, lifespan (starts supervisor), router mounting
│       ├── core/config.py        # Settings (env-driven): queues, intervals, ML URL, OSRM URL
│       ├── api/
│       │   ├── deps.py           # DB session dependency, shared service deps
│       │   └── routes/           # trips, routes, drivers, vehicles, roster, reports,
│       │                         # realtime, predictions
│       ├── models/               # SQLAlchemy models (Trip, Route, RouteStop, Vehicle,
│       │                         # Driver, OptimizationAudit, GPSBreadcrumb,
│       │                         # RealtimeFleetStatus, DelayPrediction)
│       ├── services/             # Business logic: trip_service, route_service, kpi_service,
│       │                         # eta_service, delay_prediction_service, roster_service,
│       │                         # route_optimizer, realtime_service,
│       │                         # osrm_client, weather_client, geocode_client, ml_client
│       ├── optimization/
│       │   ├── greedy/insertion.py     # Greedy best-insertion assigner
│       │   ├── regret/insertion.py     # Regret-k insertion (used by LNS repair)
│       │   ├── lns/                    # optimizer.py, destroy.py, repair.py
│       │   ├── feasibility/engine.py   # Capacity/time-window/duty feasibility checks
│       │   ├── candidates/search.py    # Candidate route discovery for a trip
│       │   ├── scoring/cost_function.py# Cost model driving all assignment decisions
│       │   ├── state.py                # Route state helpers/locks interplay
│       │   └── audit/logger.py         # OptimizationAudit writer (before/after snapshots)
│       ├── workers/              # supervisor.py, trip_assignment_worker.py,
│       │                         # lns_worker.py, trip_completion_worker.py
│       ├── infrastructure/       # queue.py (in-process Queue/Worker), locks.py (Redis locks)
│       └── simulation/engine.py  # Demo-day trip simulator (GPS breadcrumbs, progress)
├── frontend/                     # React + TS + Vite SPA
│   └── src/
│       ├── pages/LiveOpsPage.tsx # Main LiveOps screen
│       ├── components/liveops/   # PlanStrip, AlertStrip, ActivityFeed (and map panels)
│       ├── hooks/                # useLiveOps (polling), useOpsEvents (SSE),
│       │                         # useTripSimulator (demo control)
│       ├── api/                  # Typed API clients (trips, routes, realtime SSE)
│       ├── utils/                # routeColors, serviceArea, hydLocations (demo geo data)
│       └── App.tsx               # Routing/shell
├── ml/                           # ML microservice
│   ├── service/ml_api.py         # FastAPI endpoints (predict + optimize)
│   ├── models_store/             # Trained XGBoost .pkl models
│   ├── feature_contract_v2.json  # Feature schema contract for the delay model
│   └── src/
│       ├── models/               # delay_risk, eta_prediction, expected_delay,
│       │                         # fuel_consumption, trip_cost
│       └── optimizer/            # or_tools_solver, hybrid_solver, ml_windows
└── docker-compose.yml            # frontend, backend, ml, postgres, osrm
```

## 4. Data Model

Core SQLAlchemy entities (`backend/app/models/`):

| Model | Purpose / key fields |
|---|---|
| `Trip` | A customer order. Pickup/drop-off coordinates & addresses, `load_weight_kg`, time windows (`window_start`/`window_end`), `status` (`pending → assigned → in-transit → completed` / `unassigned`), `route_id` FK, delay/cost prediction fields |
| `Route` | A vehicle's day plan. `vehicle_id`, `driver_id`, `status` (`planned/active/in-transit/completed`), capacity bookkeeping (`capacity_kg`, `used_capacity_kg`, `remaining_capacity_kg`), **`version`** for optimistic concurrency |
| `RouteStop` | Ordered stops on a route: `sequence`, `stop_type` (`pickup`/`delivery`/`waypoint`), lat/lng, `eta`, time windows, `status`, cached `weather_condition` |
| `Vehicle` | Fleet assets: type (`Container Truck`, `Mini Truck`, `Refrigerated Truck`, `Trailer`, `Truck`), `load_capacity_kg`, `fuel_type` (CNG/Diesel), `avg_kmpl_rated`, `vehicle_age_years`, base location |
| `Driver` | `license_type` (HMV/HMV-Hazmat/HMV-Trailer/LMV), `experience_years`, `rating`, `base_location`, duty availability |
| `OptimizationAudit` | One row per optimization decision: run id, strategy used, cost before/after, trips reinserted, JSON `before_routes`/`after_routes` snapshots, execution time |
| `GPSBreadcrumb` | Timestamped vehicle position points produced by the simulator / telemetry, used for progress and map movement |
| `RealtimeFleetStatus` | Current per-vehicle snapshot (position, active route, load) powering the live map |
| `DelayPrediction` | Persisted ML output per trip: `delay_probability`, predicted minutes, model version, features timestamp |

Relationships: `Route 1─N RouteStop`, `Route 1─N Trip` (via `trip.route_id`), `Vehicle 1─N Route`, `Driver 1─N Route`.

---

## 5. Background Workers (`app/workers/` + `infrastructure/`)

`main.py` starts the `Supervisor` in the FastAPI **lifespan hook**. Threads are daemons so shutdown never hangs.

| Thread | Role |
|---|---|
| `trip-assignment-worker` | Consumes the `trip-assignment` queue. For each trip job: candidate search → feasibility → cost scoring → greedy insertion → commit → publish realtime events |
| `lns-worker` | Consumes the `lns-optimization` queue (jobs created **only** by the manual trigger endpoint). Runs multi-iteration LNS against the active plan |
| `trip_completion_worker` | Watches in-transit trips, advances stop statuses, marks trips/routes complete when deliveries finish |
| `UnassignedSweeper` | Every **60 s** re-enqueues up to 25 unassigned trips so the backlog drains; logs a heartbeat line so "idle" is distinguishable from "dead" in docker logs |
| `LNSScheduler` | ⚠️ **DISABLED** (kept for reference). Periodic LNS removed; re-optimization is manual-only via API |

### Queue & locking infrastructure
- `infrastructure/queue.py`: lightweight `Queue`/`Worker` abstraction (queue length introspection for the LiveOps "queue depth" KPI).
- `infrastructure/locks.py`: Redis-backed distributed locks — used to ensure only **one** LNS run / plan mutation touches a route set at a time.
- Route-level **version stamps**: a mutating optimizer checks and bumps `Route.version`; stale versions cause rollback instead of a corrupt plan.

## 6. The Optimization Engine (`app/optimization/`)

### 6.1 Pipeline for a single incoming trip (greedy)

```
trip job → candidates/search.py ─► feasibility/engine.py ─► scoring/cost_function.py
              (which routes                 (capacity, time                (score each
               could serve it?)              windows, driver               candidate position)
                                              duty hours)
                       │
                       ▼
       greedy/insertion.py: pick min-cost feasible insertion
       (pickup stop inserted before delivery stop, sequence renumbered,
        capacity bookkeeping updated, ETA recomputed)
                       │
                       ▼
       commit + OptimizationAudit + realtime event ("trip assigned")
```

- **Candidate search** enumerates feasible (route, pickup index, delivery index) slots.
- **Feasibility engine** rejects slots violating capacity, service/delivery windows, or driver duty.
- **Cost function** blends weighted terms — travel distance/duration added, lateness, load utilization, route balance (weights configurable; the same `CostFunction` is shared with LNS so greedy and LNS optimize the same objective).

### 6.2 Regret insertion (`regret/insertion.py`)
Instead of inserting the cheapest trip first, regret-k computes for each unassigned trip the **cost gap between its best and k-th-best insertion** and inserts the trip with the largest regret first — the ones that would become very expensive if their best slot were taken.

### 6.3 LNS (`lns/optimizer.py`, `destroy.py`, `repair.py`)

Multi-iteration loop on the active plan:

1. **Destroy** — remove ~`destroy_percentage` (default **20%**) of trips using one of:
   - `random_destroy` — unbiased sampling
   - `worst_cost_destroy` — remove trips whose current placement costs most
   - `related_destroy` — remove spatially/temporally related trips (Shaw-style)
   - `route_destroy` — empty whole routes (enables re-bundling)
   - `delay_destroy` — target trips with predicted delay problems
2. **Repair** — re-insert all removed trips with `greedy_repair`, `regret_2_repair`, or `regret_3_repair`.
3. **Accept** — recompute total cost with `CostFunction`; accept **only if improvement > `acceptance_threshold` (default 0)**; otherwise **rollback**.
4. **Rollback safety** (`_rollback_to_state`): snapshots every touched route (version, capacity, full stop list) and every trip's `route_id` before mutating; restores deleted `RouteStop` rows with their original PKs so a rollback reproduces the plan **bit-for-bit** and snapshots stay comparable.
5. **Audit** — writes an `OptimizationAudit` row with strategies used, old/new cost, trips reinserted, execution time, and JSON before/after route snapshots (surfaced in the UI as before/after plan comparison).

Result type `LNSResult` carries: `success`, `improvement`, `old_cost`/`new_cost`, `routes_affected`, `trips_reinserted`, `execution_time_ms`, `destroy_strategy`, `repair_strategy`, `before_routes`, `after_routes`.

Two prebuilt instances exist: `lns_optimizer` (default: RANDOM destroy + REGRET_2 repair) and `lns_optimizer_regret3` (REGRET_3 repair).

## 7. ML Microservice (`ml/`)

A separate FastAPI app (`ml/service/ml_api.py`) loaded with trained XGBoost models from `models_store/` (`*.pkl`). The backend talks to it through `app/services/ml_client.py` (HTTP); graceful degradation when the service is down (503 with clear "model not found" errors).

### 7.1 Prediction endpoints

| Endpoint | Model | Output | Feature highlights |
|---|---|---|---|
| `/predict/eta` | ETA regressor | `predicted_duration_minutes` | distance_km, num_stops, hour_of_day, day_of_week, avg historical speed |
| `/predict/delay-risk` | Delay risk classifier (25 features, contract in `ml/feature_contract_v2.json`) | `delay_probability`, `is_delayed_prediction` | vehicle type, GPS start/end, weather (Clear/Heat/Fog/Rain/Storm), road type, traffic density (Low→Severe), fuel price, driver/vehicle/route historical delay rates, license type, experience, rating |
| `/predict/expected-delay` | Delay regressor | `predicted_delay_minutes` | same feature family as delay risk |
| `/predict/fuel` | `fuel_l_xgboost_v1.pkl` | `predicted_fuel_liters` | shared 10-field cost schema: vehicle/road/traffic/weather/fuel type, distance, load, rated kmpl, age, fuel price |
| `/predict/trip-cost` | `trip_cost_xgboost_v1.pkl` | `predicted_trip_cost` | same 10-field schema (`COST_FEATURE_ORDER`) |

> The **delay model uses 25 features** while fuel/cost models share a **10-field schema** read directly from the trained booster metadata — the Pydantic request models mirror these contracts exactly and must be kept in sync on retraining.

### 7.2 Optimization endpoints (OR-Tools)

- `POST /optimize/pickup-delivery` — solves a pickup-and-delivery problem with Google **OR-Tools**:
  - Input: jobs (trip_id, pickup/delivery stop indices, load, time windows, service time), vehicles (capacity, start location, kmpl, fuel price, duty hours), distance/duration matrices, coordinates, cost weights (`alpha`, `delta`, `beta`, `gamma`, `lateness_weight`), solver time limit.
  - `solve_with_fallback` returns routes per vehicle, total duration/distance/lateness, **fuel cost (₹)**, ton-km, which solver was used, and feasibility. Falls back when OR-Tools can't find a solution.
- **ML-generated time windows** (`ml_windows.py`): `build_time_windows_for_jobs` uses the ML ETA model to auto-generate realistic time windows from coordinates + speed; `optimize_with_ml_windows` chains prediction → solving (the "hybrid solver" path).

### 7.3 How the backend consumes ML
- `services/ml_client.py`: typed async HTTP client for all prediction endpoints.
- `services/delay_prediction_service.py`: builds feature vectors from trip/vehicle/driver/route/history (persisting `DelayPrediction` rows), attaches delay risk to trips in the LiveOps UI and feeds `delay_destroy` in LNS.
- `services/eta_service.py`: combines OSRM distances/durations with ML ETAs for stop-level ETAs on routes.

## 8. External Service Integrations (`app/services/`)

| Client | Purpose |
|---|---|
| `osrm_client.py` | OSRM `table` (duration/distance matrices) and `route` (geometry for map polylines) calls; used by candidate search, ETA computation, and map drawing |
| `weather_client.py` | Weather conditions per stop area; cached onto `RouteStop.weather_condition` (feeds delay-risk features) |
| `geocode_client.py` | Address ↔ lat/lng resolution at trip creation |

All clients are async (`httpx`) with timeouts and fallback behavior so LiveOps keeps functioning if an external provider degrades.

---

## 9. API Surface (`app/api/routes/`)

| Router | Key endpoints |
|---|---|
| `trips.py` | CRUD + list w/ filters (`unassigned=true`), create trip (enqueues `trip-assignment` job), status transitions |
| `routes.py` | List active routes w/ stops, route detail, **`POST /api/routes/lns/trigger`** (manual LNS), LNS result retrieval, before/after comparison |
| `drivers.py` / `vehicles.py` | Fleet rosters (CRUD, availability) |
| `roster.py` | Combined driver+vehicle duty roster views |
| `reports.py` | KPI/report aggregations (trips per day, delays, costs) |
| `realtime.py` | **SSE stream** (`/api/realtime/events`) + fleet status snapshots |
| `predictions.py` | On-demand delay/ETA/fuel/cost predictions for a trip (proxies to ML service) |

Auth/session dependencies live in `api/deps.py` (DB session per request via SQLAlchemy).

### Real-time layer
- **Server:** `services/realtime_service.py` maintains an event bus; `realtime.py` exposes a **Server-Sent Events** endpoint. Events published: trip created/assigned/status changed, route updated, LNS completed (with improvement), KPI changes.
- **Client:** `frontend/src/hooks/useOpsEvents.ts` wraps `EventSource` (`api/realtime.ts`), feeding `LiveOpsPage` for instant updates; TanStack Query hooks (`useLiveOps.ts`) **poll** as a complementary safety net — incoming trips every **4 s**, all trips and routes every **8 s**. Route colors are stable per route (`utils/routeColors.ts`).

---

## 10. Simulation Engine (`app/simulation/engine.py`)

For demos and testing without a real fleet:
- Generates trips from a Hyderabad service-area dataset (`frontend/src/utils/hydLocations.ts` mirrors the geography).
- Advances trips through their lifecycle over time, emitting **GPS breadcrumbs** (`GPSBreadcrumb` rows) and updating `RealtimeFleetStatus` so vehicles visibly move on the map.
- Drives stop status transitions so the `trip_completion_worker` can close trips/routes naturally.
- Frontend control via `useTripSimulator.ts` (start/stop/pace the demo day from the UI).

---

## 11. Frontend Deep Dive

| Area | Files | Notes |
|---|---|---|
| Main screen | `pages/LiveOpsPage.tsx` | Composition of map + KPI strips + incoming queue + activity feed + alert strip |
| Plan strip | `components/liveops/PlanStrip.tsx` | Today's plan summary (active routes, loads, completion) |
| Alert strip | `components/liveops/AlertStrip.tsx` | Surfaces delay-risk, stuck unassigned trips, LNS results |
| Activity feed | `components/liveops/ActivityFeed.tsx` | Chronological event stream from SSE + polling merge |
| Data hooks | `hooks/useLiveOps.ts` | `useIncomingTrips` (4 s), `useAllTripsLive` (8 s, limit 1000 to avoid silent KPI clipping), `useRoutesLive` (8 s, filters to planned/active/in-transit) |
| SSE | `hooks/useOpsEvents.ts`, `api/realtime.ts` | EventSource subscription; keeps UI live between polls |
| Map utils | `utils/serviceArea.ts`, `hydLocations.ts`, `routeColors.ts` | Service-area polygon, demo locations, deterministic route colors |

State/data-fetching convention: **TanStack Query** with `refetchInterval` for polling + query-key invalidation from SSE events. No global store; server state lives in the query cache.

## 12. Deployment (`docker-compose.yml`)

| Service | Image/Build | Notes |
|---|---|---|
| `frontend` | Node/Vite build served via static server | Talks to backend over HTTP + SSE |
| `backend` | Python + Uvicorn | Runs FastAPI app **including worker threads** (supervisor started in lifespan); env vars for DB URL, ML URL, OSRM URL, queue/interval settings |
| `ml` | Python (xgboost, ortools) | Loads `models_store/*.pkl` at startup |
| `postgres` | PostgreSQL | Single source of truth for trips/routes/roster/audits |
| `osrm` | OSRM server | Pre-built road network for matrices/routing |

Run everything: `docker compose up --build` (backend available at the API port, frontend on the Vite/served port, ML service internally).

---

## 13. Configuration (`core/config.py` — env-driven settings)

| Setting | Meaning |
|---|---|
| `TRIP_ASSIGNMENT_QUEUE` | Queue name consumed by the assignment worker |
| `LNS_INTERVAL_MINUTES` | Retained for the (disabled) periodic scheduler; LNS is manual via API |
| ML service base URL | Target for `ml_client` predictions |
| OSRM / weather / geocode base URLs | External providers |
| DB URL | SQLAlchemy Postgres DSN |

---

## 14. End-to-End Flow (trace summary)

1. `POST /api/trips` → trip persisted (`pending`) → `trip-assignment` job enqueued → SSE `trip.created`.
2. Worker pops job → candidate search → feasibility → cost scoring → **greedy insertion** → capacity/ETA updates → SSE `trip.assigned` + audit log.
3. No feasible slot? Trip stays `unassigned`; the **sweeper** re-enqueues every 60 s.
4. Dispatcher hits `POST /api/routes/lns/trigger` → `lns-optimization` job → LNS destroy/repair iterations → accept-if-better + rollback safety → `OptimizationAudit` row → SSE `lns.completed` with improvement %, before/after snapshots.
5. Simulator/telemetry emits breadcrumbs → stop statuses advance → `trip_completion_worker` closes trips/routes → KPIs and reports refresh.
6. Frontend stays live through SSE events + 4–8 s polling; AlertStrip highlights delay-risky trips (ML) and backlog.

---

## 15. Design Decisions & Trade-offs

- **In-process workers vs. external broker:** simpler deployment for demo scale; the `Queue`/`Worker` abstraction leaves the door open to swap in Celery/RQ/Redis streams later.
- **Manual LNS:** automatic global re-optimization can surprise dispatchers mid-shift; manual trigger keeps accountability (and each run is audited). The disabled `LNSScheduler` shows the periodic path is a config flip away.
- **Optimistic concurrency (route `version`) + Redis locks:** protects against double-assignment when API and workers race.
- **Bit-for-bit rollback:** LNS restores original `RouteStop` primary keys so audit snapshots remain diffable — chosen over "delete-and-recreate" which would break comparability.
- **Two optimization tiers:** greedy for latency (seconds per trip), LNS for quality (batched global improvement) — a standard PDPTW production pattern.
- **ML as a sidecar service:** independent scaling/retraining cadence; strict Pydantic feature contracts (`feature_contract_v2.json`) prevent train/serve skew.

## 16. Extension Ideas

- Re-enable periodic LNS behind a "low-traffic window" schedule.
- Wire ML trip-cost into quoting/pricing at trip creation.
- Add WebSocket bidirectional channel for dispatcher actions on alerts.
- Persist OSRM geometries for offline map replay; add traffic-layer overlays.
- CI: unit tests for feasibility/cost/insertion invariants, golden-file tests for LNS rollback snapshots.

---

*See also: `README.md`, `ROQIT_PLATFORM.md`, `USER_GUIDE.md`, and `LIVEOPS_EXECUTIVE_OVERVIEW.md`.*






