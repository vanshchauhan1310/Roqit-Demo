# RoQit — Fleet Optimization Platform

A full-stack **dynamic fleet optimization platform**: trips stream in, a background
engine assigns each one to a route in real time (greedy best-insertion), and a
periodic **LNS** optimizer keeps re-arranging the whole plan to reduce cost.
Three independently deployable parts — `frontend`, `backend`, `ml` — that work
together over HTTP.

- **frontend/** — React + TypeScript + Vite, TailwindCSS, React Query, React Router, Recharts, Leaflet.
- **backend/** — FastAPI + SQLAlchemy + Alembic, backed by PostgreSQL (hosted on [Supabase](https://supabase.com)), with an in-process Redis-backed job queue and worker threads.
- **ml/** — Standalone Python service (scikit-learn/XGBoost) exposing `/predict/*` endpoints, called by the backend over HTTP so it can scale/deploy separately.

This README documents **all the logic used across the system** — the algorithms,
the rules, the thresholds, and where each one lives in the code.

> Deeper reading: [README2.md](README2.md) (route-builder / TSP / ETA code
> walkthrough) · [ROQIT_PLATFORM.md](ROQIT_PLATFORM.md) (platform blueprint) ·
> [USER_GUIDE.md](USER_GUIDE.md) (UI walkthrough) ·
> [MANUAL_TEST_GUIDE.md](MANUAL_TEST_GUIDE.md) (acceptance checklist).

---

## 1. Architecture at a glance

```
┌──────────────┐  POST /api/trips   ┌────────────────────────────────────┐
│   frontend   │ ─────────────────► │   backend (FastAPI :8000)          │
│  React :5173 │ ◄─ poll ~2-5s ──── │  ├─ REST API (routers + services)  │
│  Live Ops UI │                    │  ├─ Redis queue (job lists)        │
└──────────────┘                    │  └─ lifespan → Supervisor threads: │
┌──────────────┐  HTTP /predict/*   │      1. trip-assignment worker     │
│    ml        │ ◄───────────────── │      2. LNS worker                 │
│  :8001       │                    │      3. LNS scheduler (every N min)│
└──────────────┘                    │      4. unassigned-trips sweeper   │
┌──────────────┐   SQLAlchemy       ├────────────────────────────────────┤
│  Supabase    │ ◄───────────────── │  external HTTP (stateless calls):  │
│ (PostgreSQL) │                    │  OSRM · Nominatim · OpenWeather    │
└──────────────┘                    └────────────────────────────────────┘
```

- **Supervisor** (`backend/app/workers/supervisor.py`) is started by the FastAPI
  **lifespan hook** (`backend/app/main.py`) — you never run workers separately.
  All four threads are daemons, so process shutdown never hangs.
- **Queue** (`backend/app/infrastructure/queue.py`) is Redis-backed:
  pending jobs live in the list `queue:<name>` (LPUSH enqueue / BRPOP dequeue
  with a 5s timeout); delayed retries live in the sorted set
  `queue:<name>:delayed` and are promoted to the main list when due.

---

## 2. Data model & status lifecycles

Core tables (`backend/app/models/`): `trips`, `routes`, `route_stops`,
`vehicles`, `drivers`.

- **trip → route (M:1)** — an assigned trip has a non-null `trip.route_id`
  (a denormalized `String` FK, set by greedy insertion and cleared by LNS
  destroy). A trip with `route_id IS NULL` is **unassigned / incoming**.
- **route_stop** — the ordered tour of a route. `stop_type` ∈
  `pickup | delivery | waypoint`; sequence ordering enforces **pickup before
  delivery** for every trip's P/D pair.
- IDs are human-facing strings: `TRP-XXXXXXXX`, `VEH…`, `DRV…` and UUIDs for
  `route_id` / `stop_id`.

### Trip status transitions — lazily computed
There is **no background status job**. `trip_service._apply_auto_status_transition`
(`backend/app/services/trip_service.py`) advances status **every time a trip is
read** (`get_trip` / `list_trips`):

```
scheduled ──(now >= pickup_time)──► in-transit ──(now >= actual_delivery_time)──► delivered
```

It only touches `scheduled` / `in-transit` — a manually-set
`Delayed` / `Cancelled` / `Delivered` status is never overridden.
Routes get the same treatment (`route_service._apply_auto_status_transition`):
`planned → in-transit` once `pickup_time` passes.

### Trip creation — derived fields
`trip_service.create_trip` fills in everything a dispatcher can't reliably know
(rule-based, clearly labeled, not ML):

| Field | Logic |
|---|---|
| `status` | `"scheduled"` |
| `actual_distance_km` | `planned_distance_km × 1.12` (demo overage factor) |
| `actual_delivery_time` | `planned_delivery_time + 45 min` |
| `weather_condition` | ML service prediction from start coords (`weather_client`) |
| `road_type` | `"Highway"` if `planned_distance_km ≥ 15` else `"City Road"` |
| `traffic_density` | `High` 8-9,17-19h · `Medium` 7,10,16,20h · else `Low` |
| `fuel_price_per_l` | `DEFAULT_FUEL_PRICE_PER_L` (92.5) — no live feed |
| validation | rejects `load_weight_kg` above the named vehicle's capacity |

---

## 3. Async ingestion pipeline (trip → queue → worker)

```
POST /api/trips ──► persist trip (status=scheduled, route_id=NULL)
      │ returns 202 {"trip_ref": ..., "status": "RECEIVED"} immediately
      └─► queue.enqueue("trip-assignment", {trip_id})
                 │
                 ▼
     trip-assignment worker (BRPOP, 5s timeout)
                 │ handle_job → _assign_trip
                 ▼
      greedy_insertion.assign_trip(db, trip)
```

**Retry logic** (`queue.py: Worker._process_job`): a job whose handler returns
`False` (exception, trip vanished, DB error) is requeued with delay
`retry_delay × attempt` (60s, 120s, 180s) and dropped after 3 attempts.

**Safety net — UnassignedSweeper** (`supervisor.py:48`,
`trip_assignment_worker.sweep_unassigned_trips`): every **60s** it re-enqueues up
to **25** trips that still have `route_id IS NULL` and status
`scheduled`/`unassigned`. This drains any backlog created while the worker was
down or a job was lost — it's why Live Ops "queue depth" returns to ~0 when the
feed is idle.

---

## 4. The live assignment engine (greedy best insertion)

File: `backend/app/optimization/greedy/insertion.py` (+ `candidates/search.py`,
`feasibility/engine.py`, `scoring/cost_function.py`). Four stages run for every
trip:

```
1. Candidate search   → which existing routes could take this trip?
2. Position search    → every valid (pickup, delivery) insertion position
3. Feasibility check  → hard constraints only; any violation ⇒ reject
4. Cost scoring       → weighted cost; minimum wins
      │ no feasible insertion anywhere
      ▼
5. Fallback: create a NEW route (vehicle + driver selection below)
```

### 4.1 Candidate search (`candidates/search.py`)

Multi-stage filter, then a composite score (higher = better). Limits:
`max_candidates = 50`, `max_pickup_distance_km = 50`, `min_capacity_buffer = 0.1`.

| Stage | Rule |
|---|---|
| Status | route ∈ `planned / active / in-transit` |
| Vehicle | `vehicle_type` must equal the trip's hint (if the trip has one) |
| Capacity | remaining capacity ≥ `load × 1.1` (10% safety buffer) |
| Geography | haversine distance from the route's current position (or last stop) to the trip's pickup ≤ 50 km |
| Time / direction | stubs (`return True`) — TODO |

**Score = utilization (0–30) + closeness (0–30) + driver rating (0–20) +
driver experience (0–10) + fewer-stops bonus (0–20).** Top 50 by score move on.

### 4.2 Feasibility engine (`feasibility/engine.py`) — hard constraints

Any *hard* violation makes the candidate position infeasible. Defaults:
`max_route_duration_hours = 12`, `max_detour_factor = 1.5`,
`max_delay_minutes = 60`, `max_wait_minutes = 30`.

1. **Capacity** — vehicle load capacity is never exceeded.
2. **Vehicle compatibility** — type match.
3. **Driver constraints** — `LICENSE_MISMATCH` when the trip requires a
   license the driver doesn't have (only checked when the trip has one).
4. **Route duration** — post-insertion tour ≤ 12h, estimated network-free:
   haversine ÷ 40 km/h (per-leg OSRM calls here would turn one assignment into
   hundreds of HTTP round-trips — road-accurate routing is used only where it
   matters, in display/ETA).
5. **Time windows**.
6. **Frozen stops** — stops with `sequence ≤ route.frozen_until_sequence`
   (committed deliveries) must not move.
7. **Delay impact** — stub (TODO).
8. **Detour factor** — stub (TODO).
9. **Precedence** — pickup sequence < delivery sequence for every trip.
10. **Geographic compatibility** — stub (TODO).

### 4.3 Cost function (`scoring/cost_function.py`)

Weighted sum of insertion *deltas* (what the route gains by taking this trip):

| Component | Weight | How it's computed |
|---|---|---|
| Extra distance (km) | 0.30 | haversine tour length before vs. after |
| Extra duration (min) | 0.25 | haversine ÷ 40 km/h, before vs. after |
| Delay impact (min) | 0.20 | slip on downstream stops' windows |
| Fuel cost (₹) | 0.10 | ML fuel-cost estimate service |
| Delay risk | 0.10 | traffic/window risk + driver-rating proxy (≤ 1.0) |
| Change penalty | 0.05 | 2.0 per reordered existing stop, 10.0 if stop count breaks |

Weights auto-normalize to sum 1.0 (`CostWeights.normalize`), so they're tunable.

### 4.4 Greedy insertion & apply (`greedy/insertion.py`)

- For every candidate route, **all** valid `(pickup_seq, delivery_seq)` pairs
  are enumerated (pickup before delivery) and scored; the global minimum-cost
  option wins.
- `apply_insertion` writes the new `RouteStop` rows, renumbers sequences,
  **bumps `route.version`** (optimistic locking), sets `trip.route_id`, and
  commits.

### 4.5 Fallback — new route creation (`trip_assignment_worker._create_new_route`)

When no existing route is feasible:

- **Vehicle** — least-loaded-first policy: only `active` (or legacy NULL-status)
  vehicles of the matching type whose `load_capacity_kg ≥ trip.load`, and whose
  current committed load (sum of `used_capacity_kg` over `planned/active/
  in-transit` routes) + this trip stays under capacity. Among eligible vehicles
  the one with the **most headroom** wins (deterministic tie-break by
  `vehicle_id`) so work spreads across the fleet.
- **Driver** — only `active` (or NULL-status) drivers, with
  **exact** `license_type` match, respecting **14 h hours-of-service**: a
  driver's already-assigned estimated hours (haversine ÷ 40 km/h + 0.1 h per
  stop, over `planned/active/in-transit` routes) plus the new trip's estimate
  must stay ≤ `MAX_DRIVER_HOS_HOURS = 14`. Among eligible drivers the
  **least-loaded** wins.
- The route is created with P/D stops (sequences 1–2) and audited as
  `NEW_ROUTE_CREATED`.
- **If no vehicle or no driver qualifies**, the trip is marked
  `status="unassigned"` and **not retried** (a business decision, not an error)
  — it is audited as `ASSIGNMENT_FAILED`. The sweeper will keep re-offering it,
  so a permanently-unassignable trip (e.g. a license type no driver holds, or
  all drivers HOS-capped) shows up as a stuck non-zero **queue depth**.

---

## 5. LNS — periodic global re-optimization

Files: `backend/app/optimization/lns/optimizer.py`, `lns/destroy.py`,
`lns/repair.py`, `workers/lns_worker.py`.

**Large Neighborhood Search** improves the *whole* plan, not one trip:

1. Snapshot the live plan and compute the baseline cost.
2. **Destroy** — remove ~`LNS_DESTROY_PERCENTAGE` (20%) of trips from the plan.
   Strategies: `RANDOM` (default), `WORST_COST`, `RELATED`, `ROUTE`, `DELAY`.
   Destroying a trip clears its `trip.route_id`.
3. **Repair** — re-insert the removed trips using the same feasibility engine
   and cost function. Strategies: `GREEDY`, `REGRET-2` (default),
   `REGRET-3`. Regret-k inserts the trip whose *best-vs-k-th-best* cost gap is
   largest first — it protects the choices that would be most expensive to
   postpone.
4. **Accept / reject** — hill-climbing: a candidate better than the current plan
   is committed and the search continues from it; a worse one is rolled back.
   The live plan is therefore **monotonically never worse** than the baseline.
5. Loop until `LNS_MAX_ITERATIONS` (30) or `LNS_ITERATION_BUDGET_SECONDS` (90).
   Every accepted iteration compounds. Before/after plan snapshots and the
   improvement are logged for audit (`PERIODIC_LNS`).

**Triggers:**
- `LNSScheduler` thread enqueues an `lns-optimization` job every
  `LNS_INTERVAL_MINUTES` (default 10);
- the **⚡ LNS button** in Live Ops KPI band enqueues the same job on demand
  (`POST /api/routes/{id}/optimize` → job → 202);
- the simulation engine runs LNS every N trips during replays.

Guard rails: needs ≥ 2 routes to run; skipped harmlessly otherwise.

---

## 6. Simulation & benchmark engine

File: `backend/app/simulation/engine.py`. Replays historical trips from a CSV
(ordered by timestamp, `speed_factor` > 1 to fast-forward) through the **real**
assignment worker and LNS worker, and reports:
trips assigned/unassigned, routes created, total distance/duration, fuel cost,
route utilization, assignment latency, and greedy-vs-LNS cost.

- `run_from_csv(...)` — pure replay; optionally runs LNS every N trips.
- `run_greedy_vs_lns_comparison(csv)` — resets the optimization state, replays
  greedy-only, replays greedy+LNS (every 50 trips), and reports the
  `improvement_percentage` — this is the "engine's value" number the Live Ops
  **⚡ LNS → Engine savings** tile alludes to.
- Cost model for comparisons: `0.30 × km + 0.25 × hours` (same weight
  philosophy as the cost function).

---

## 7. Manual route building & static TSP optimization

Deep walkthrough: [README2.md](README2.md). Summary of the logic:

- **Geocoding** — Nominatim (OpenStreetMap) with a required identifying
  User-Agent; results cached on stops.
- **Live preview** — the frontend calls OSRM directly for the drawn polyline;
  the backend is not in that loop.
- **Optimization** (`backend/app/services/route_optimizer.py`) — fetches a real
  OSRM `/table` **duration/distance matrix**, groups stops into
  pickup-delivery jobs, adds a depot node (explicit or first stop), then
  **delegates the combinatorial search to the ML service's OR-Tools optimizer**
  (`ml_client.optimize_pickup_delivery_route`) with a 10 s solver time limit.
  The backend owns the real-world I/O; the ML service owns the solver.
  Two solvers exist, chosen by stop count (exact search for small problems,
  heuristic for large) — see README2 §6.3.

---

## 8. ETA & weather logic

File: `backend/app/services/eta_service.py`, `weather_client.py`.

- **Base duration** — real OSRM route duration when available.
- **Weather adjustment** — a hand-coded, rule-based multiplier table
  (`WEATHER_ETA_MULTIPLIERS`) applied to the base duration, keyed by the ML
  service's weather-condition prediction at the trip's start coordinates:
  `adjusted = base × multiplier`.
- **Predicted delivery time** = `pickup_time + adjusted duration`.
- **Fallback chain** — ML ETA model (XGBoost duration-minutes regression,
  feature contract `ml/feature_contract_v2.json`) if available, else the
  rule-based OSRM + weather estimate. Every response labels which path was
  used — never silently mixing provenance.

---

## 9. Live Ops dashboard — telemetry logic

Files: `frontend/src/pages/LiveOpsPage.tsx`, `hooks/useLiveOps.ts`,
`hooks/useOpsEvents.ts`, `hooks/useTripSimulator.ts`,
`components/liveops/*`.

**KPI band** (polling, ~2–5 s, react-query):

| Tile | Logic |
|---|---|
| Queue depth | count of `GET /api/trips?unassigned=true` — trips with no `RouteStop` reference. Normally 0; a stuck non-zero value means trips are failing assignment (see §4.5) |
| Trips today | total trip count in session |
| Active routes | count of routes |
| Fleet utilization | `Σ used_capacity_kg / Σ capacity_kg` across active routes |
| Avg assignment | latency from RECEIVED event → route_id, via `useOpsEvents` diffing |

**Event feed** — `useOpsEvents` diffs consecutive polls into an event stream:
new trip → `RECEIVED`, `route_id` appears → `ASSIGNED` (+ latency), new route →
`NEW ROUTE CREATED`, LNS → `PLAN UPDATED`. The amber pulsing map dot marks
incoming (unassigned) trips; each route keeps a stable djb2-hash color across
renders so the map never visually jitters.

**Auto feed (trip simulator)** — entirely client-side, hitting the real
`POST /api/trips` so every simulated trip goes through the real
queue → greedy → LNS pipeline:
- one trip every **60 s** (countdown ring; toggle persisted in `localStorage`);
- origin/destination = random **Hyderabad** locations (destination ≠ origin);
- `load_weight_kg` = 200–1400 kg, `vehicle_type = "Truck"`, GPS coordinates
  filled in directly (no geocoding needed).

---

## 10. Audit trail

File: `backend/app/optimization/audit/logger.py` → `optimization_audit` table.
**Every** engine decision is persisted (not just printed):

| Audit type | When |
|---|---|
| `ONLINE_GREEDY` | trip inserted into an existing route (position, cost, deltas, `greedy-v1`) |
| `NEW_ROUTE_CREATED` | fallback route created (`greedy-v1`) |
| `ASSIGNMENT_FAILED` | no vehicle / no driver (reason recorded) |
| `PERIODIC_LNS` | LNS run (`lns-v1`, improvement, before/after snapshots) |

This table is the ground truth for debugging "why is trip X unassigned?"

---

## 11. ML service (port 8001)

- `POST /predict/eta` — XGBoost duration-minutes regression
  (contract: `ml/feature_contract_v2.json`).
- `POST /predict/delay` — trip delay prediction; the backend validates
  features against bounds in `delay_prediction_service.py` before calling.
- `POST /predict/fuel-cost` — fuel burn/cost estimate used by the cost
  function's fuel component.
- `POST /optimize/pickup-delivery` — OR-Tools VRP with pickup-delivery
  constraints + time windows (used by the manual route optimizer).
- The backend **never imports ML code** — always HTTP, so the ML service can
  be redeployed/scaled independently. If it's down, rule-based fallbacks kick
  in and responses say so.

---

## 12. Configuration knobs (`backend/app/core/config.py`, via `.env`)

| Variable | Default | Controls |
|---|---|---|
| `DATABASE_URL` | local Postgres | Supabase connection (`postgresql+psycopg2://…?sslmode=require`) |
| `REDIS_URL` | `redis://localhost:6379/0` | queue backend |
| `ML_SERVICE_URL` | `http://localhost:8001` | predictions + VRP solver |
| `GREEDY_MAX_CANDIDATES` | 50 | candidate routes scored per trip |
| `GREEDY_MAX_PICKUP_DISTANCE_KM` | 50.0 | candidate geo filter |
| `LNS_INTERVAL_MINUTES` | 10 | scheduler cadence |
| `LNS_DESTROY_PERCENTAGE` | 0.2 | share of trips destroyed per iteration |
| `LNS_MAX_ITERATIONS` | 30 | destroy/repair loops per run |
| `LNS_ITERATION_BUDGET_SECONDS` | 90 | wall-clock cap per run |
| `OSRM_BASE_URL` | public demo server | routing matrices + geometry |
| `NOMINATIM_URL` / `GEOCODE_USER_AGENT` | OSM | geocoding (UA required by policy) |
| `OPENWEATHER_API_KEY` | — | per-stop weather for ETA |
| `DEFAULT_FUEL_PRICE_PER_L` | 92.5 | fuel pricing input |

---

## 13. Known limitations / TODOs (by design, documented)

- Feasibility checks **7 (delay impact)** and **8 (detour factor)** are stubs;
  candidate search's time-window and direction checks are `return True` stubs.
- Driver HOS accounting has **no daily reset** — `_driver_worked_hours` sums
  all `planned/active/in-transit` routes ever, so in a long session every
  driver eventually saturates and new-route creation fails with
  "No available driver" (the #1 suspect for a stuck queue depth).
- Driver `license_type` matching is **exact equality** in new-route creation —
  a driver with a different license string is never eligible.
- The UnassignedSweeper re-offers hard-unassignable trips every 60 s, so they
  churn in the audit log (`ASSIGNMENT_FAILED`) — intentional for demo honesty,
  noisy at scale.
- No live fuel-price or GPS feed — demo-derived values (§2) and haversine
  estimates stand in; OSRM/road-accurate routing is used where users see it.

---

## 14. Running everything

### Database

This project uses [Supabase](https://supabase.com) (hosted Postgres) instead of
a local Postgres container. Create a Supabase project, grab the connection
string from **Project Settings > Database > Connection string (URI)**, and put
it in `backend/.env` as `DATABASE_URL` (see `backend/.env.example` for the
exact format — note the `postgresql+psycopg2://` scheme and
`?sslmode=require`).

### With Docker

```bash
cp backend/.env.example backend/.env   # fill in your Supabase DATABASE_URL
docker-compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (docs at /docs, health at /health)
- ML service: http://localhost:8001 (health at /health)

### Locally (without Docker)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # fill in your Supabase DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload --port 8000   # lifespan auto-starts the workers
```

```bash
# Frontend
cd frontend
cp .env.example .env
npm install
npm run dev
```

```bash
# ML service
cd ml
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/train.py --model eta --input data/raw/trips.csv   # train the example ETA model
uvicorn service.ml_api:app --reload --port 8001
```

There is also `./run-all-dev.ps1` (Windows) to start all three at once.

### Seed the demo fleet (Docker)

The engine needs active vehicles + drivers to assign trips — an empty fleet
sends every trip to the unassigned queue ("No available vehicle / driver").
Seed once after the first `up`:

```bash
docker compose exec backend python seed_fleet.py
```

Idempotent (safe to re-run): 10 vehicles (8 Trucks sized 2–16 t, plus a Tempo
and a Trailer) and 6 HMV drivers, all `active`, based in Hyderabad — matched to
what the auto-feed generates (Truck, 200–1400 kg, Hyderabad). Trips created
while the fleet was empty are recovered automatically by the unassigned
sweeper within ~60 s of seeding.

---

## 15. Where to add new features

| Adding...                                   | Goes in...                                                        |
|----------------------------------------------|---------------------------------------------------------------------|
| A new API resource (CRUD)                     | `backend/app/models/`, `schemas/`, `services/`, `api/routes/`      |
| A new DB table/column                         | `backend/app/models/` + `alembic revision --autogenerate`          |
| A new optimization constraint                 | `backend/app/optimization/feasibility/engine.py` (`_check_*`)      |
| A new cost component                          | `backend/app/optimization/scoring/cost_function.py` + `CostWeights`|
| A new LNS destroy/repair strategy             | `backend/app/optimization/lns/destroy.py` / `repair.py`            |
| New frontend page                             | `frontend/src/pages/` + register the route in `App.tsx`            |
| New Live Ops widget                           | `frontend/src/components/liveops/`                                 |
| Reusable UI (buttons, tables, modals)         | `frontend/src/components/common/`                                   |
| New API call from the frontend                | `frontend/src/api/` + a hook in `frontend/src/hooks/`               |
| A new ML model                                | `ml/src/models/` (train/predict), wire into `ml/src/train.py`, add an endpoint in `ml/service/ml_api.py` |
| Backend calling a new ML endpoint             | `backend/app/services/ml_client.py`                                 |

## 16. Conventions

- IDs are named consistently with the schema: `trip_id`, `driver_id`,
  `vehicle_id`, `route_id`, `stop_id`.
- All URLs, DB credentials, and API keys come from environment variables — see
  `.env.example` in `frontend/` and `backend/`. Never commit real `.env` files.
- The backend never imports ML code directly — it always calls the `ml` service
  over HTTP, so ML can be scaled or redeployed independently.
- Optimization internals are network-free haversine (40 km/h assumed) so the
  hot loop stays sub-second; OSRM is reserved for user-visible routing/ETA.
- Every engine decision is auditable — if you add a decision path, add an
  audit row for it.

