# Roqit — Real-Time Dynamic Route Optimization & Trip Assignment Platform

> **A production-grade online vehicle-routing platform.** Trips stream in continuously; each is assigned in real time by a **Greedy Best-Insertion** heuristic, and the global plan is periodically improved by a **Large Neighborhood Search (LNS)** — all running behind a live command centre where every engine decision is visible on a map and in a streaming event feed.

**Stack:** React 18 + TypeScript (Vite) · FastAPI + Uvicorn · SQLAlchemy · PostgreSQL · Redis · XGBoost · OSRM · Leaflet · Tailwind CSS · TanStack Query · Docker Compose

---

## 1. Quick Start

### One-command start (Docker)

```powershell
cd "C:\Users\Vanshraj\OneDrive - Aion Tech Solutions Ltd (ATS)\Desktop\Roqit-Demo"
docker compose up -d
docker compose ps             # wait for all 5 services → "healthy"
```

Open **http://localhost:5173** → click **Live Ops** in the sidebar.

> **Never run two backend instances.** Duplicate instances = duplicate worker threads on the same Redis queues.

### Running locally (without Docker)

```powershell
# Backend — lifespan auto-starts all 4 worker threads
cd backend; .venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# ML service (separate terminal — needed for predictions)
cd ml; venv\Scripts\activate
python -m uvicorn service.ml_api:app --host 0.0.0.0 --port 8001

# Frontend (separate terminal)
cd frontend; npm install; npm run dev
```

---

## 2. Service Roles & Ports

| Container | Port | Responsibility |
|-----------|------|----------------|
| `frontend` | 5173 | React SPA + nginx — serves UI, proxies `/api` → backend |
| `backend` | 8000 | FastAPI — HTTP routes + 4 background worker threads + DB layer |
| `ml` | 8001 | ML service — XGBoost models (delay risk, ETA, fuel, trip cost) + OR-Tools |
| `postgres` | 5432 | Single source of truth — trips, routes, stops, drivers, vehicles, audit |
| `redis` | 6379 | Async job queues (`trip-assignment`, `lns-optimization`) + writer-funnel locks |
| `osrm` (optional) | 5000 | OSRM routing engine — falls back to public demo server if not running |

**Optional services degrade gracefully:** OSRM unavailable → haversine distance estimates. No weather API key → defaults to `"Clear"`.
---

## 3. Architecture

### 3.1 Topology

```
                         ┌──────────────────────────────────────────────────┐
  CLIENT                 │            Docker Compose (single host)          │
  http://localhost:5173  │  ┌──────────────┐        ┌───────────────┐      │
 ──────────────►         │  │ nginx  :5173 │ proxy  │  React SPA    │      │
                         │  └──────────────┘        └──────┬────────┘      │
                         │                          │        │  /api/*     │
  ┌────────────┐         │  ┌──────────────┐ ┌─────►│  API GW      │      │
  │  Browser   │         │  │   nginx      │ │      └──────┬────────┘      │
  │  Leaflet,  │         │  └──────────────┘ │             │               │
  │  Tailwind  │         │         ▼                      │               │
  └────────────┘         │  ┌────────────────┐            │               │
                         │  │ FastAPI  :8000 │            │               │
                         │  │   Uvicorn    │            │               │
                         │  └──┬──┬──┬──┬───┘            │               │
                         │     │  │  │  │                 │               │
  ┌────────────┐         │ ┌───┘  │  │  │  ┌─────────────┘               │
  │  PostgreSQL│         │ ▼      ▼  ▼  ▼                          │
  │  :5432     │◄────────┼─│ trips  │ │routes │    ┌────────────────┐ │
  │  (Supabase)│         │ │ drivers│ │stops  │    │  Redis  :6379   │ │
  └────────────┘         │ │vehicles│ │audit  │    │ live ops queue │ │
                         │ └────────┘ └───────┘    │ trip-assign…   │ │
                         │                          │ lns-queue      │ │
                         │                          └────────────────┘ │
                         │                           │                │
                         │ ┌──────────────┐           │                │
                         │ │ ML svc :8001│◄──────────┼─────────┐    │
                         │ │ OR-Tools    │           │         │    │
                         │ └──────────────┘           ▼         ▼    │
                         │            OSRM :5000        │  (LNS worker) │
                         └───────────────────────────────────────────────┘
```

### 3.2 Background Workers

The `Supervisor` (`backend/app/workers/supervisor.py`) spawns **4 daemon threads** inside the API process — started by the FastAPI lifespan hook (`backend/app/main.py:21-27`):

| Thread | Queue / Interval | Role |
|--------|-----------------|------|
| **Trip Assignment Worker** | `queue:trip-assignment` — continuous Redis consumer (5s BRPOP timeout) | Pops jobs → greedy best-insertion → assigns trip to best route or creates new route |
| **LNS Worker** | `queue:lns-optimization` — manual trigger only | Destroys ~20% of plan → repairs via regret-2 → accepts only if cost improves → full atomic rollback |
| **Unassigned Sweeper** | 60-second heartbeat | Re-enqueues trips with no RouteStop (max 25/batch) so backlog drains |
| **Trip Completion Worker** | 180-second heartbeat | Auto-completes trips 10 min after assignment → frees vehicle/driver → re-predicts ML for affected routes |

---

## 4. The Assignment Engine

### 4.1 Trip Lifecycle

```
T=0.0s   POST /api/trips
           │
           ▼
         Trip created: status="scheduled", route_id=NULL, vehicle_id=NULL, driver_id=NULL
           │
           ▼
         create_trip_assignment_job(trip_id) → Redis queue:trip-assignment
           │
           ▼
         API returns 202 RECEIVED (async — assignment is background)

           ▼  milliseconds later if worker is idle
  ┌─────────────────────────┐
  │ TripAssignmentWorker    │
  │ 1. acquire_writer_lock  │  Redis advisory lock — serializes with LNS + completion
  │ 2. validate_trip_assign│  checks RouteStop existence (not just route_id NULL)
  │ 3. greedy_insertion     │  candidate_search → feasibility → cost scoring → best insertion
  │ 4. apply_insertion      │  creates RouteStop(pickup) + RouteStop(delivery)
  │ 5. audit_log            │  OptimizationAudit row
  │ 6. release_lock         │
  └─────────────────────────┘
           │
           ▼
         Trip now has: route_id, vehicle_id, driver_id, assigned_at
           │
           ▼  10 min later (demo lifecycle)
  ┌─────────────────────────┐
  │ TripCompletionWorker    │  sweep every 180s
  │ status="completed"      │  frees cargo weight → route capacity recomputed
  │ route completed if last │  frees vehicle + driver for new work
  │ re-predict ML           │  for affected routes
  └─────────────────────────┘
```

### 4.2 Greedy Best-Insertion

**File:** `backend/app/optimization/greedy/insertion.py`

For each incoming trip:
1. **Candidate Search** — routes where pickup is within `GREEDY_MAX_PICKUP_DISTANCE_KM` (50 km default)
2. **Feasibility Check** — capacity, driver HOS, time windows, route duration
3. **Cost Scoring** — 6 weighted components:
   ```
   cost = 0.30 × extra_distance_km
        + 0.25 × extra_duration_minutes
        + 0.10 × delay_impact_minutes
        + 0.10 × fuel_cost_rupees
        + 0.10 × delay_risk           ← ML or rule-based (traffic/weather/road)
        + 0.05 × route_change_penalty
   ```
4. **Select minimum cost** feasible insertion
### 4.4 Delay Risk in Cost Function

The inline `delay_risk` component is a **fast heuristic** (not the ML prediction) — combines route/driver historical delay rates with traffic/weather/road type risks. Returns 0.0–1.0.

The ML `delay_probability` prediction (XGBoost `delay_risk_xgboost_v2`) is computed separately on-demand when the frontend requests it via `/api/predictions/delay/trips/{trip_id}`.

---

## 5. LNS — Large Neighborhood Search

**File:** `backend/app/optimization/lns/optimizer.py`

1. **Destroy** — remove ~20% of trips from routes (`LNS_DESTROY_PERCENTAGE = 0.2`)
   - Strategies: `RANDOM`, `ROUTE_BASED`, `WORST_COST`
2. **Repair** — re-insert in optimal order
   - Strategies: `GREEDY`, `REGRET_2`, `REGRET_3` (regret = "how much does it hurt to leave this trip out")
3. **Accept/Reject** — only keep if total cost improved
4. **Atomic Rollback** — restore original `RouteStop` primary keys if rejected (preserves audit comparability)

**Manual trigger:**
```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/routes/lns/trigger"
# Returns 202 + job_id; run takes 6-10s
```

Results appear as SSE events + `OptimizationAudit` rows in the database.

---

## 6. Frontend — LiveOps Page

**File:** `frontend/src/pages/LiveOpsPage.tsx`

| Component | What it shows |
|-----------|---------------|
| **KPI Tiles** | Queue depth, trips today, active routes, fleet utilization %, avg assignment latency (sparklines, last 40 samples), auto-feed controller (Pause/Start/+Trip/⚡LNS buttons) |
| **Event Feed** | Streaming log: RECEIVED, ASSIGNED (with latency), NEW ROUTE, PLAN UPDATED, LNS triggered — color-coded + timestamped |
| **Live Map** | Dark Leaflet map, Hyderabad bounds, amber pulsing dots = incoming trips, numbered stop markers, stable-color route polylines, animated flight lines on assignment |
| **Plan Strip** | One row per route — P/D chips pop in with spring animation + live capacity bar |
### 6.1 Polling + SSE

```typescript
// frontend/src/hooks/useLiveOps.ts
// Called from LiveOpsPage with custom intervals:
useIncomingTrips(3000)   // GET /api/trips?unassigned=true  — 3s poll
useAllTripsLive(5000)    // GET /api/trips (limit 1000)     — 5s poll
useRoutesLive(5000)      // GET /api/routes                 — 5s poll
```

| Hook | Poll Interval | Endpoint | What it fetches |
|------|--------------|----------|-----------------|
| `useIncomingTrips` | **3 seconds** | `GET /api/trips?unassigned=true` | Trips with no RouteStop — the "incoming queue" |
| `useAllTripsLive` | **5 seconds** | `GET /api/trips` (limit 1000) | All trips — used for event diffing + KPI counts |
| `useRoutesLive` | **5 seconds** | `GET /api/routes` | All routes, filtered to active statuses |

Plus **SSE** (`useOpsEvents.ts` → `EventSource` to `/api/events/stream`) for instant updates between polls. The `useOpsEvents` hook diffs polling results into human-readable events.

> **Important:** The 3s polling is a **display refresh rate**, NOT the assignment engine's cadence. The assignment worker runs continuously on a Redis queue with sub-second reaction time. If assignment completes in <3s (very common), the trip appears in the UI already fully assigned — driver, vehicle, and delay risk included. This is expected behavior, not a bug.

### 6.2 Trip Simulator (Demo Auto-Feed)

**File:** `frontend/src/hooks/useTripSimulator.ts`

Posts 1 new Hyderabad-only trip every 60 seconds via `POST /api/trips`. Runs entirely client-side against the real API — goes through the real queue → greedy → LNS pipeline. Controlled from the KPI band: **Pause/Start feed**, **+Trip** (fire immediately), countdown ring.

---

## 7. API Reference

### 7.1 Trips

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/trips` | Create trip → `202 RECEIVED` → enqueues assignment job |
| `GET` | `/api/trips` | List trips (paginated, filterable by status/driver/pickup_date/search) |
| `GET` | `/api/trips?unassigned=true` | Trips with no RouteStop — the "incoming queue" |
| `GET` | `/api/trips/{trip_id}` | Single trip detail |
| `PATCH` | `/api/trips/{trip_id}/status` | Update trip status |
| `GET` | `/api/trips/{trip_id}/eta-prediction` | Rule-based weather-adjusted ETA |
| `GET` | `/api/trips/{trip_id}/fuel-cost-estimate` | Fuel cost estimate |
| `GET` | `/api/trips/{trip_id}/cost-prediction` | Full ML trip cost prediction |
| `GET` | `/api/trips/{trip_id}/vehicle-intelligence` | Vehicle insights (needs assigned vehicle) |
| `GET` | `/api/trips/{trip_id}/driver-intelligence` | Driver insights (needs assigned driver) |
| `PATCH` | `/api/trips/{trip_id}/outcome` | Record real delivery outcome (Delivered/Delayed) |

**Trip creation body:**
```json
{
  "origin": "Madhapur",
  "destination": "Gachibowli",
  "gps_start_lat": 17.4483,
  "gps_start_lon": 78.3915,
  "gps_end_lat": 17.4401,
  "gps_end_lon": 78.3489,
  "load_weight_kg": 1200,
  "vehicle_type": "Truck"
}
```
Weather, road_type, traffic_density, fuel_price_per_l are auto-filled if omitted.

### 7.2 Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/routes` | List all routes with stops |
| `GET` | `/api/routes/{route_id}` | Route detail |
| `POST` | `/api/routes/lns/trigger` | Manual LNS → `202` + `job_id` |

### 7.3 Predictions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/predictions/delay/trips/{trip_id}` | ML delay risk for specific trip |
| `POST` | `/api/predictions/delay/latest` | Predict for GPS-latest active trip |
| `POST` | `/api/predictions/expected-delay/trips/{trip_id}` | Expected delay in minutes |

### 7.4 Realtime

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/events/stream` | SSE stream of live ops events |

### 7.5 Fleet

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` / `POST` | `/api/drivers` | Driver roster CRUD |
| `GET` / `POST` | `/api/vehicles` | Vehicle roster CRUD |

### 7.6 Health

| Method | Endpoint |
|--------|----------|
| `GET` | `/health` |
| **Alert Strip** | Delay-risk flags (ML), stuck unassigned trips, LNS results |
| **Detail Drawer** | Slide-over: vehicle + driver, capacity, stop sequence table, delay risk, weather, GPS |
5. **Fallback** — no feasible route? Create new route with available driver + vehicle (ensures assignment *never fails* due to capacity constraints alone)

**Key files:** `greedy/insertion.py`, `candidates/search.py`, `feasibility/engine.py`, `scoring/cost_function.py`

### 4.3 Writer Funnel Lock

All route/trip mutations serialized through Redis advisory lock `lock:fleet-plan-write`:
- Assignment worker: 75s lock timeout (queues behind LNS instead of failing)
- LNS worker: holds lock for every destroy/repair iteration (up to 90s budget)
- Completion worker: skips sweep if lock busy, retries next 180s cycle

### 4.4 Delay Risk in Cost Function

The inline `delay_risk` component is a **fast heuristic** (not the ML prediction) — combines route/driver historical delay rates with traffic/weather/road type risks. Returns 0.0–1.0.

The ML `delay_probability` prediction (XGBoost `delay_risk_xgboost_v2`) is computed separately on-demand when the frontend requests it via `/api/predictions/delay/trips/{trip_id}`.

---

## 5. LNS — Large Neighborhood Search

**File:** `backend/app/optimization/lns/optimizer.py`

1. **Destroy** — remove ~20% of trips from routes (`LNS_DESTROY_PERCENTAGE = 0.2`)
   - Strategies: `RANDOM`, `ROUTE_BASED`, `WORST_COST`
2. **Repair** — re-insert in optimal order
   - Strategies: `GREEDY`, `REGRET_2`, `REGRET_3` (regret = "how much does it hurt to leave this trip out")
3. **Accept/Reject** — only keep if total cost improved
4. **Atomic Rollback** — restore original `RouteStop` primary keys if rejected (preserves audit comparability)

**Manual trigger:**
```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/routes/lns/trigger"
# Returns 202 + job_id; run takes 6-10s
```

Results appear as SSE events + `OptimizationAudit` rows in the database.

---

## 6. Frontend — LiveOps Page

**File:** `frontend/src/pages/LiveOpsPage.tsx`

| Component | What it shows |
|-----------|---------------|
| **KPI Tiles** | Queue depth, trips today, active routes, fleet utilization %, avg assignment latency (sparklines, last 40 samples), auto-feed controller (Pause/Start/+Trip/⚡LNS buttons) |
| **Event Feed** | Streaming log: RECEIVED, ASSIGNED (with latency), NEW ROUTE, PLAN UPDATED, LNS triggered — color-coded + timestamped |
| **Live Map** | Dark Leaflet map, Hyderabad bounds, amber pulsing dots = incoming trips, numbered stop markers, stable-color route polylines, animated flight lines on assignment |
| **Plan Strip** | One row per route — P/D chips pop in with spring animation + live capacity bar |
| **Alert Strip** | Delay-risk flags (ML), stuck unassigned trips, LNS results |
| **Detail Drawer** | Slide-over: vehicle + driver, capacity, stop sequence table, delay risk, weather, GPS |
| **Detail Drawer** | Slide-over: vehicle + driver, capacity, stop sequence table, delay risk, weather, GPS |

### 6.1 Polling + SSE

```typescript
// frontend/src/hooks/useLiveOps.ts
// Called from LiveOpsPage with custom intervals:
useIncomingTrips(3000)   // GET /api/trips?unassigned=true  — 3s poll
useAllTripsLive(5000)    // GET /api/trips (limit 1000)     — 5s poll
useRoutesLive(5000)      // GET /api/routes                 — 5s poll
```

| Hook | Poll Interval | Endpoint | What it fetches |
|------|--------------|----------|-----------------|
| `useIncomingTrips` | **3 seconds** | `GET /api/trips?unassigned=true` | Trips with no RouteStop — the "incoming queue" |
| `useAllTripsLive` | **5 seconds** | `GET /api/trips` (limit 1000) | All trips — used for event diffing + KPI counts |
| `useRoutesLive` | **5 seconds** | `GET /api/routes` | All routes, filtered to active statuses |

Plus **SSE** (`useOpsEvents.ts`) for instant updates between polls. The `useOpsEvents` hook diffs polling results into human-readable events (RECEIVED → trip first seen, ASSIGNED → route_id appeared, etc.).

> **Important:** The 3s polling is a **display refresh rate**, NOT the assignment engine's cadence. The assignment worker runs continuously on a Redis queue with sub-second reaction time. If assignment completes in <3s (very common), the trip appears in the UI already fully assigned — driver, vehicle, and delay risk included. This is expected behavior, not a bug.

### 6.2 Trip Simulator (Demo Auto-Feed)

**File:** `frontend/src/hooks/useTripSimulator.ts`

Posts 1 new Hyderabad-only trip every 60 seconds via `POST /api/trips`. Runs entirely client-side against the real API — goes through the real queue → greedy → LNS pipeline. Controlled from the KPI band: **Pause/Start feed**, **+Trip** (fire immediately), countdown ring.

---

## 7. API Reference

### 7.1 Trips

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/trips` | Create trip → `202 RECEIVED` → enqueues assignment job |
| `GET` | `/api/trips` | List trips (paginated, filterable by status/driver/pickup_date/search) |
| `GET` | `/api/trips?unassigned=true` | Trips with no RouteStop — the "incoming queue" |
| `GET` | `/api/trips/{trip_id}` | Single trip detail |
| `PATCH` | `/api/trips/{trip_id}/status` | Update trip status |
| `GET` | `/api/trips/{trip_id}/eta-prediction` | Rule-based weather-adjusted ETA |
| `GET` | `/api/trips/{trip_id}/fuel-cost-estimate` | Fuel cost estimate |
| `GET` | `/api/trips/{trip_id}/cost-prediction` | Full ML trip cost prediction |
| `GET` | `/api/trips/{trip_id}/vehicle-intelligence` | Vehicle insights (needs assigned vehicle) |
| `GET` | `/api/trips/{trip_id}/driver-intelligence` | Driver insights (needs assigned driver) |
| `PATCH` | `/api/trips/{trip_id}/outcome` | Record real delivery outcome (Delivered/Delayed) |

**Trip creation body:**
```json
{
  "origin": "Madhapur",
  "destination": "Gachibowli",
  "gps_start_lat": 17.4483,
  "gps_start_lon": 78.3915,
  "gps_end_lat": 17.4401,
  "gps_end_lon": 78.3489,
  "load_weight_kg": 1200,
  "vehicle_type": "Truck"
}
```
Weather, road_type, traffic_density, fuel_price_per_l are auto-filled if omitted.

### 7.2 Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/routes` | List all routes with stops |
| `GET` | `/api/routes/{route_id}` | Route detail |
| `POST` | `/api/routes/lns/trigger` | Manual LNS → `202` + `job_id` |

### 7.3 Predictions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/predictions/delay/trips/{trip_id}` | ML delay risk for specific trip |
| `POST` | `/api/predictions/delay/latest` | Predict for GPS-latest active trip |
| `POST` | `/api/predictions/expected-delay/trips/{trip_id}` | Expected delay in minutes |

### 7.4 Realtime

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/events/stream` | SSE stream of live ops events |

### 7.5 Fleet

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` / `POST` | `/api/drivers` | Driver roster CRUD |
| `GET` / `POST` | `/api/vehicles` | Vehicle roster CRUD |

### 7.6 Health

| Method | Endpoint |
|--------|----------|
| `GET` | `/health` |

---

## 8. Data Model

### 8.1 Key Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `trips` | Customer orders | `trip_id`, `status` (scheduled/assigned/in-transit/completed), `route_id`, `vehicle_id`, `driver_id`, `assigned_at`, `gps_*`, `load_weight_kg`, `weather_condition`, `road_type`, `traffic_density`, `pickup_time`, `planned_delivery_time` |
| `routes` | Vehicle day plans | `route_id`, `vehicle_id`, `driver_id`, `status` (planned/active/in-transit/completed), `capacity_kg`, `used_capacity_kg`, `remaining_capacity_kg`, `version` (optimistic lock) |
| `route_stops` | Ordered stops on a route | `stop_id`, `route_id`, `trip_id`, `sequence`, `stop_type` (pickup/delivery/waypoint), `latitude`, `longitude`, `address` |
| `driver_master` | Driver roster | `driver_id`, `driver_name`, `license_type`, `experience_years`, `rating`, `base_location`, `status` |
| `vehicle_master` | Vehicle roster | `vehicle_id`, `vehicle_type`, `load_capacity_kg`, `fuel_type`, `avg_kmpl_rated`, `year`, `status` |
| `optimization_audit` | Every engine decision logged | `assignment_status` (ASSIGNED/NEW_ROUTE/FAILED/UNASSIGNED), `cost`, `distance_delta`, `duration_delta`, `delay_delta`, `algorithm_version` |
| `delay_predictions` | Persisted ML predictions | `trip_id`, `delay_probability` (0–1), `is_delayed_prediction`, `model_version` (e.g. `delay_risk_xgboost_v2` or `rule_based_fallback`) |

### 8.2 Trip Status Auto-Transition

```python
# backend/app/services/trip_service.py:_apply_auto_status_transition
# Called on every trip read — lazy, no background scheduler needed:
# - "scheduled" → if pickup_time has passed → "in-transit"
```

The trip completion worker is the **only** thing that sets `status="completed"`.

### 8.3 Assignment State Classification

```python
# backend/app/optimization/state.py:TripAssignmentStatus
# A trip is VALIDly assigned ONLY when ALL of:
# 1. route_id is set
# 2. the referenced route exists
# 3. at least one RouteStop exists for the trip
# 4. that RouteStop's route_id matches trip.route_id
# 5. trip.vehicle_id and trip.driver_id are populated (not NULL)
#
# States: VALID, ORPHANED, MISSING_ROUTE_STOP, MISMATCHED_ROUTE, MISSING_RESOURCES, UNASSIGNED
```

---

## 9. ML / Prediction Pipeline

**Model:** `delay_risk_xgboost_v2` (XGBClassifier trained on 1298 trips)

**Feature contract:** `ml/feature_contract_v2.json` - exactly 25 fields with categorical vocabularies and numeric ranges.

**Pipeline:**
```
Trip -> engineer_features (25-field payload)
     -> validate (null checks -> category vocab -> numeric ranges)
     -> POST ml:8001/predict/delay (XGBoost)
     -> store in delay_predictions table
     -> return JSON to frontend
```

**Fallback (ML unreachable):** Deterministic rule-based score. `model_version = rule_based_fallback`.

**Models served by ML container (port 8001):**

| Model | Endpoint | Output |
|-------|----------|--------|
| `delay_risk_xgboost_v2` | `/predict/delay` | `delay_probability` (0-1) + `is_delayed_prediction` |
| Expected-delay regressor | `/predict/expected-delay` | `predicted_delay_minutes` |
| Fuel consumption | `/predict/fuel-liters` | `predicted_fuel_liters` |
| Trip cost | `/predict/trip-cost` | cost estimate |

---

## 10. Configuration
All settings are env-driven via `backend/app/core/config.py`:

| Setting | Default | Meaning |
|---------|---------|--------|
| `DATABASE_URL` | `postgresql+psycopg2://fleet:fleet@localhost:5432/fleet_db` | Postgres connection |
| `ML_SERVICE_URL` | `http://localhost:8001` | ML service base URL |
| `BACKEND_CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origin |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for queues + locks |
| `TRIP_ASSIGNMENT_QUEUE` | `trip-assignment` | Queue name for assignment jobs |
| `QUEUE_CONCURRENCY` | 5 | Queue worker concurrency |
| `GREEDY_MAX_CANDIDATES` | 50 | Max candidate routes to evaluate |
| `GREEDY_MAX_PICKUP_DISTANCE_KM` | 50.0 | Max distance from pickup to route for candidacy |
| `LNS_DESTROY_PERCENTAGE` | 0.2 | Fraction of trips to destroy in LNS |
| `LNS_MAX_ITERATIONS` | 30 | Max destroy/repair cycles per LNS run |
| `LNS_ITERATION_BUDGET_SECONDS` | 90 | Time budget per LNS run |
| `DEFAULT_FUEL_PRICE_PER_L` | 92.5 | Default fuel price |
| `GREEDY_ALGORITHM_VERSION` | `greedy-v1` | Algorithm version tag |
| `LNS_ALGORITHM_VERSION` | `lns-v1` | Algorithm version tag |

**Cost function weights** (normalized to sum to 1.0):

| Component | Weight |
|-----------|--------|
| Distance | 0.30 |
| Time | 0.25 |
| Delay impact (min) | 0.10 |
| Fuel cost (INR) | 0.10 |
| Delay risk | 0.10 |
| Change penalty | 0.05 |

---

## 11. Verification & Testing

### 11.1 Health checks
```powershell
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### 11.2 Smoke test
```powershell
$base = "http://localhost:8000/api"
$trip = irm $base/trips -Method Post -Body (@{origin="Madhapur";destination="Gachibowli";gps_start_lat=17.4483;gps_start_lon=78.3915;gps_end_lat=17.4401;gps_end_lon=78.3489;load_weight_kg=1200;vehicle_type="Truck"} | ConvertTo-Json) -ContentType "application/json"
do { Start-Sleep 2; $t = irm "$base/trips/$($trip.trip_ref)" } while ($t.route_id -eq $null)
irm $base/routes/lns/trigger -Method Post
curl.exe -N http://localhost:8000/api/events/stream
```

### 11.3 Working-correctly checklist
- `/health` returns 200
- `POST /api/trips` returns 202 RECEIVED immediately
- Every trip obtains a `route_id` within seconds
- Trips cluster into shared routes; distant ones create new routes
- Pickup always precedes delivery for every trip
- Capacity never exceeded
- LNS trigger returns 202 + audit row; zero trips lost after LNS
- No `Worker error:` lines flooding server log

### 11.4 Backend test scripts
| Script | What it does |
|--------|-------------|
| `unit_checks.py` | Optimization primitives (no DB writes) |
| `smoke_test_http.py` | HTTP-level smoke test |
| `fix_prediction_data.py` | Repair trips missing ML-required fields |
| `seed_fleet.py` | Seed demo fleet |
| `seed_demo_data.py` | Seed comprehensive demo data |

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Trips stay `route_id=NULL` forever | Worker not running, or duplicate backend instances | Restart single backend; check for duplicate `app.main:app` processes |
| `ASSIGNMENT_FAILED ... No available vehicle` | No active vehicle | Seed vehicles with `status:"active"` |
| `502 Optimization service unavailable` | ML service on 8001 down | Restart ML: `uvicorn service.ml_api:app --port 8001` |
| `Worker error: Timeout reading from socket` | Old build | Restart backend |
| Redis unreachable | Redis not started | Start Redis; check port 6379 |
| Docker daemon won\\'t start | Docker Desktop not running | Restart Docker Desktop, then `docker compose up -d` |
| Prediction returns 500 | `feature_contract_v2.json` not in backend container | Bind mount: `./ml/feature_contract_v2.json:/ml/feature_contract_v2.json:ro` |
| Prediction returns 422 | Trip missing required model fields | Run `fix_prediction_data.py` or re-seed |
| Trip appears with driver/vehicle already set | Assignment completed in <3s - faster than 3s poll. Expected. | Check backend logs for timestamps |

---

## 13. Seeding Demo Data

Fresh Docker DB auto-seeds drivers + vehicles. To add more:

```powershell
$base = "http://localhost:8000/api"
irm $base/drivers -Method Post -Body (@{driver_id="DRV001";driver_name="Ravi Kumar";status="active";license_type="LMV";experience_years=5;rating=4.5} | ConvertTo-Json) -ContentType "application/json"
irm $base/vehicles -Method Post -Body (@{vehicle_id="VEH001";vehicle_type="Truck";status="active";load_capacity_kg=8000;avg_kmpl_rated=8.0} | ConvertTo-Json) -ContentType "application/json"
```

**One-off seed scripts:** `seed_fleet.py` (demo fleet), `seed_demo_data.py` (comprehensive demo data).

---

## 14. Stopping / Resetting

```powershell
docker compose stop          # graceful stop - data preserved
docker compose start         # resume
docker compose down -v       # full reset - wipes DB + Redis
docker compose logs -f       # stream all logs live
```

---

## 15. Project Structure

Roqit-Demo/
├── backend/app/
│   ├── main.py              # FastAPI + lifespan (starts supervisor)
│   ├── api/routes/          # trips.py, routes.py, drivers.py, vehicles.py, predictions.py, realtime.py, ...
│   ├── core/config.py       # All env-driven settings
│   ├── db/                  # base.py + session.py (pool_size=12)
│   ├── models/              # Trip, Route, RouteStop, Driver, Vehicle, OptimizationAudit, DelayPrediction...
│   ├── optimization/
│   │   ├── greedy/insertion.py    # GreedyBestInsertion
│   │   ├── candidates/search.py   # Candidate route search
│   │   ├── feasibility/engine.py  # Feasibility checks
│   │   ├── scoring/cost_function.py # 6-component weighted cost
│   │   ├── lns/optimizer.py       # LNS destroy/repair/accept-reject
│   │   ├── audit/logger.py        # OptimizationAudit writer
│   │   └── state.py               # TripAssignmentStatus, locks, sync helpers
│   ├── services/             # trip_service, route_service, delay_prediction_service, ...
│   ├── workers/              # supervisor, trip_assignment_worker, lns_worker, trip_completion_worker
│   └── infrastructure/       # queue.py (Redis), locks.py (Redis advisory locks)
├── frontend/src/
│   ├── pages/LiveOpsPage.tsx  # Main mission-control screen
│   ├── hooks/useLiveOps.ts    # Polling hooks (3s/5s)
│   ├── hooks/useOpsEvents.ts  # SSE + diff -> events
│   ├── hooks/useTripSimulator.ts # 1-trip/min auto-feed
│   ├── components/liveops/    # KPI tiles, map, plan strip, alert strip, activity feed, drawer
│   ├── api/                   # Typed API clients
│   └── types/                 # Trip, Route, DelayPrediction, LnsRun, etc.
├── ml/                       # ML service: ml_api.py, src/models, src/features, src/optimizer, models_store
├── docs/                     # All project documentation (see Section 16)
├── docker-compose.yml         # 5-service orchestration
└── .env.example               # Environment variable template
```

---

## 16. Docs Folder - Important Files

All project documentation is consolidated in `docs/`:

| File | Audience | Content |
|------|----------|--------|
| `README.md` | Everyone | Root entry point - architecture, quick start, API, troubleshooting (this file) |
| `ROQIT_PLATFORM.md` | Everyone | Full platform documentation - topology, components, manual test guide, engine details |
| `LIVEOPS_EXECUTIVE_OVERVIEW.md` | Business stakeholders | Executive summary - capabilities, value, glossary, day-in-the-life |
| `LIVEOPS_TECHNICAL_GUIDE.md` | Engineers | Technical reference - architecture, data model, algorithms, API, SSE, polling, config, design decisions |
| `MANUAL_TEST_GUIDE.md` | QA / testers | Manual test procedures - prerequisites, test suite, verification checklist, troubleshooting, load test |
| `USER_GUIDE.md` | End users | LiveOps screen walkthrough - KPI band, event feed, map, plan builder, detail drawer, creating trips |
| `PREDICTION_MODEL_DECK.md` | Data engineers / ML | Prediction pipeline deep-dive - feature contract, root causes, fixes, verification |

---

*Roqit - real-time, self-optimizing fleet dispatch. Open http://localhost:5173 -> Live Ops and watch it run.*
