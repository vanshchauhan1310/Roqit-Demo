# Manual Test Guide — Real-Time Dynamic Route Optimization & Trip Assignment

This guide explains how to run and manually verify the online dynamic routing
platform: trips stream in via `POST /api/trips`, a queue worker assigns each
one to the best feasible route using **Greedy Best-Insertion** (creating a new
route when nothing is feasible), and a **Large Neighborhood Search (LNS)**
worker periodically improves the global plan.

---

## 1. Architecture at a glance

```
external trip source ──► POST /api/trips ──► Redis queue (trip-assignment)
                                                  │
                                                  ▼
                                   TripAssignmentWorker (in API process)
                                   ├─ candidate search (existing routes)
                                   ├─ greedy best-insertion (cost scoring)
                                   └─ fallback: create new route (vehicle+driver)
                                                  │
                                                  ▼
                                   LNS worker + scheduler
                                   (destroy: random/route/worst, repair: greedy/regret-2/3)
                                                  │
                                                  ▼
                                   Postgres (routes, route_stops, trips, audit tables)
```

Key files:
- `backend/app/workers/trip_assignment_worker.py` — online assignment
- `backend/app/workers/lns_worker.py` + `app/workers/supervisor.py` — periodic LNS
- `backend/app/optimization/greedy/insertion.py` — best-insertion algorithm
- `backend/app/optimization/lns/optimizer.py` — LNS with rollback
- `backend/app/optimization/audit/logger.py` — writes `optimization_runs` / `route_assignments`

---

## 2. Prerequisites

| Service | Port | How to check |
|---|---|---|
| PostgreSQL (Supabase) | cloud | configured in `backend/.env` |
| Redis | 6379 | `Test-NetConnection 127.0.0.1 -Port 6379` |
| Backend API (FastAPI) | 8000 | `GET http://127.0.0.1:8000/health` |
| ML service | 8001 | `GET http://127.0.0.1:8001/health` (optional for routing; used by /predictions) |

### Start the backend (single instance!)

```powershell
cd "C:\Users\Vanshraj\OneDrive - Aion Tech Solutions Ltd (ATS)\Desktop\Roqit-Demo\backend"
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The FastAPI **lifespan hook auto-starts the background workers** — you do NOT
run workers separately:
- `trip-assignment-worker` thread — consumes `queue:trip-assignment`
- `lns-worker` thread — consumes `queue:lns-optimization`
- `lns-scheduler` thread — enqueues LNS every `LNS_INTERVAL_MINUTES` (see `.env`)

### Start the ML service (optional, for prediction endpoints)

```powershell
cd "C:\Users\Vanshraj\OneDrive - Aion Tech Solutions Ltd (ATS)\Desktop\Roqit-Demo\ml"
.\venv\Scripts\python.exe -m uvicorn service.ml_api:app --host 0.0.0.0 --port 8001
```

> ⚠ **Never run two instances of the backend.** Duplicate instances means
> duplicate worker threads competing on the same Redis queues. Verify first:
> ```powershell
> Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
>   Where-Object { $_.CommandLine -like '*app.main:app*' }
> ```

---

## 3. Automated test suite (run these first)

All from the `backend\` folder:

```powershell
.\venv\Scripts\python.exe unit_checks.py      # optimization primitives (no DB writes)
.\venv\Scripts\python.exe integration_test.py # greedy pipeline against live DB, self-cleaning
.\venv\Scripts\python.exe lns_test.py         # LNS destroy/repair + rollback integrity
$env:E2E_PREFIX='E2E'; .\venv\Scripts\python.exe e2e_test.py  # full HTTP end-to-end
```

| Test | Verifies |
|---|---|
| unit_checks | sync-safe cost function, no `NameError` in capacity check, real `Driver` model, async OSRM call |
| integration_test | greedy assignment of 4 trips into one route, correct pickup-before-delivery precedence, audit rows persisted |
| lns_test | LNS runs, trips never lost, **no duplicate stops** after rollback, audit rows |
| e2e_test | full HTTP flow: seed → POST trips → worker assignment → LNS trigger → consistency |

All four must print `... PASSED`.

---

## 4. Manual testing walkthrough

### 4.1 Open the API docs

Open `http://127.0.0.1:8000/docs` (Swagger UI) — every step below can be done
from there instead of PowerShell.

### 4.2 Seed a driver and two vehicles

```powershell
$base = "http://127.0.0.1:8000/api"

Invoke-RestMethod -Method Post -Uri "$base/drivers" -ContentType "application/json" -Body (@{
  driver_id = "DRV001"; driver_name = "John Doe"; status = "active"
  license_type = "LMV"; experience_years = 5; rating = 4.5
} | ConvertTo-Json)

Invoke-RestMethod -Method Post -Uri "$base/vehicles" -ContentType "application/json" -Body (@{
  vehicle_id = "VEH001"; vehicle_type = "Truck"; status = "active"
  load_capacity_kg = 8000; avg_kmpl_rated = 8.0
} | ConvertTo-Json)

Invoke-RestMethod -Method Post -Uri "$base/vehicles" -ContentType "application/json" -Body (@{
  vehicle_id = "VEH002"; vehicle_type = "Truck"; status = "active"
  load_capacity_kg = 8000; avg_kmpl_rated = 8.0
} | ConvertTo-Json)
```

(Re-running returns 409 "already exists" — that is fine.)

### 4.3 Stream trips (the real ingestion path)

```powershell
$trips = @(
  @{ lat1=51.96; lon1=4.12; lat2=52.09; lon2=5.12; load=900 },  # Rotterdam -> Utrecht
  @{ lat1=52.09; lon1=5.12; lat2=52.31; lon2=4.89; load=700 },  # Utrecht  -> Amsterdam
  @{ lat1=52.31; lon1=4.89; lat2=52.08; lon2=4.31; load=1100 }, # Amsterdam-> Den Haag
  @{ lat1=52.08; lon1=4.31; lat2=51.92; lon2=4.48; load=600 },  # Den Haag -> Rotterdam
  @{ lat1=51.44; lon1=5.48; lat2=51.92; lon2=4.48; load=800 }   # Eindhoven-> Den Haag
)
foreach ($t in $trips) {
  $r = Invoke-RestMethod -Method Post -Uri "$base/trips" -ContentType "application/json" -Body (@{
    status = "scheduled"; origin = "O"; destination = "D"
    gps_start_lat = $t.lat1; gps_start_lon = $t.lon1
    gps_end_lat = $t.lat2;  gps_end_lon = $t.lon2
    load_weight_kg = $t.load; vehicle_type = "Truck"
  } | ConvertTo-Json)
  Write-Output "enqueued $($r.trip_ref) -> $($r.status)"
}
```

Expected: each returns `{"trip_ref":"TRP-XXXXXXXX","status":"RECEIVED"}` (202).
Assignment happens **asynchronously** — do not expect a route in the response.

> **Note:** `trip_id` is generated server-side (`TRP-XXXXXXXX`); the client
> cannot choose it.

### 4.4 Watch the worker assign them

Within ~1–5 seconds per trip, check the server console (or `server.log`):

```
Processing trip assignment for TRP-XXXXXXXX
No feasible route for trip TRP-XXXXXXXX, creating new route   <- 1st trip
[AUDIT] NEW_ROUTE_CREATED trip=TRP-XXXXXXXX route=<uuid> vehicle=VEH001 driver=DRV001
Created new route <uuid> for trip TRP-XXXXXXXX
[AUDIT] GREEDY_ASSIGNMENT trip=TRP-YYYYYYYY route=<same uuid> cost=53.22 ... feasible=True
Assigned trip TRP-YYYYYYYY to route <same uuid>                <- inserted into existing route
```

Geographically-close trips (Rotterdam/Utrecht/Amsterdam/Den Haag cluster)
should land on **one shared route**; the outlying Eindhoven trip should get a
**new route** — that is the engine choosing a new route over a huge detour.

Verify via API:

```powershell
Invoke-RestMethod "$base/trips?limit=10" | Format-Table trip_id, status, route_id
Invoke-RestMethod "$base/routes?limit=10" | Format-Table name, status, vehicle_id, used_capacity_kg
```

Every trip must now have a `route_id`.

### 4.5 Inspect a route's stop sequence

```powershell
$routes = Invoke-RestMethod "$base/routes?limit=10"
$routeId = $routes[0].route_id
Invoke-RestMethod "$base/routes/$routeId"
```

Verify the invariants manually:
- every trip has exactly **one `pickup` and one `delivery` stop**
- for each trip, the pickup `sequence` < delivery `sequence`
- `used_capacity_kg` equals the sum of assigned trip loads
- the route's `status` is `planned` (or `active` if already running)

### 4.6 Test the "no feasible route → new route" path

Send a trip that cannot fit anywhere (far away / nearly a full truck):

```powershell
Invoke-RestMethod -Method Post -Uri "$base/trips" -ContentType "application/json" -Body (@{
  status = "scheduled"; origin = "Far"; destination = "Away"
  gps_start_lat = 48.85; gps_start_lon = 2.35   # Paris
  gps_end_lat = 45.76;  gps_end_lon = 4.84      # Lyon
  load_weight_kg = 7900; vehicle_type = "Truck"
} | ConvertTo-Json)
```

Expected: a **new route** is created for it (or, if no vehicle at all matches,
the trip is marked `unassigned` and `ASSIGNMENT_FAILED` is audited).

### 4.7 Test capacity rejection

```powershell
Invoke-RestMethod -Method Post -Uri "$base/trips" -ContentType "application/json" -Body (@{
  status = "scheduled"; origin = "Heavy"; destination = "Load"
  gps_start_lat = 51.96; gps_start_lon = 4.12
  gps_end_lat = 52.09;  gps_end_lon = 5.12
  load_weight_kg = 99999; vehicle_type = "Truck"   # > any vehicle capacity
} | ConvertTo-Json)
```

Expected: HTTP `422` (load exceeds the largest vehicle) — the trip is rejected
at ingestion, not silently lost.

### 4.8 Trigger and verify LNS

```powershell
Invoke-RestMethod -Method Post -Uri "$base/routes/lns/trigger"
```

Expected: `202 {"message":"LNS optimization queued","job_id":...}`.
Watch the console:

```
Running periodic LNS optimization...
[AUDIT] LNS_RUN old_cost=362.38 new_cost=264.22 improvement=98.16 accepted=True routes_affected=3 trips_reinserted=4 ...
LNS optimization completed: improvement=98.16
```

- If LNS **finds a better plan** -> accepted; routes/stops/trip assignments change.
- If it **finds no improvement** -> rejected; the plan is **rolled back exactly**
  (all trips keep their routes, no stop is duplicated or lost).

After the run, re-check:

```powershell
Invoke-RestMethod "$base/trips?limit=10" | Format-Table trip_id, route_id   # nobody lost
```

The scheduler also triggers this automatically every `LNS_INTERVAL_MINUTES`.

### 4.9 Verify the audit trail in the database

```powershell
cd backend; .\venv\Scripts\python.exe -c @"
from app.db.session import SessionLocal
from app.models.optimization_audit import OptimizationRun
db = SessionLocal()
for r in db.query(OptimizationRun).order_by(OptimizationRun.created_at.desc()).limit(15):
    print(r.optimization_type, r.trip_id, r.route_id, r.improvement_pct, r.algorithm_version)
"@
```

Expected row types: `ONLINE_GREEDY`, `NEW_ROUTE_CREATED`, `ASSIGNMENT_FAILED`,
`PERIODIC_LNS` — one per decision, persisted (not just printed).

### 4.10 Idempotency / duplicate-trip check

POST the same trip twice -> the second attempt returns `409 Conflict`, and the
worker assigns it only once.

---

## 5. What "working correctly" means — checklist

- [ ] `/health` returns 200 on the backend
- [ ] POST `/api/trips` returns `202 RECEIVED` immediately (async contract)
- [ ] Every trip obtains a `route_id` within seconds (watch server log)
- [ ] Trips cluster into shared routes; distant/infeasible ones create new routes
- [ ] Pickup always precedes delivery for every trip in every route
- [ ] Capacity never exceeded (`used_capacity_kg <= capacity_kg`)
- [ ] LNS trigger returns 202 and produces an audit row (`PERIODIC_LNS`)
- [ ] After LNS: zero trips lost, zero duplicate stops, zero unassigned regressions
- [ ] `optimization_runs` / `route_assignments` tables fill up as decisions happen
- [ ] No `Worker error:` lines flooding the server log

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Trips stay `route_id=None` forever | worker not running, or duplicate backend instances | restart a single backend instance; check process list |
| `ASSIGNMENT_FAILED ... No available vehicle` | no active vehicle with type+capacity | seed vehicles with `status:"active"` (schema now defaults to `active`) |
| `502 Optimization service unavailable` from `/api/routes/optimize` | ML service on 8001 down or crashed | restart ML: `uvicorn service.ml_api:app --port 8001` |
| `Worker error: Timeout reading from socket` spam | old build; queue client without keepalive | already fixed (`socket_keepalive=True, health_check_interval=30`, `TimeoutError` handled); restart backend |
| Duplicate pickup/delivery stops on a route | old LNS rollback bug | already fixed (rollback deletes non-snapshot stops) |
| `duplicate key ... driver_master_pkey` in test scripts | leftovers from crashed run | fixed — tests pre-clean; just re-run |
| Redis unreachable | Redis not started | start Redis, check port 6379 |

---

## 7. Load / stress test (optional)

Blast 50 trips and measure assignment latency:

```powershell
Measure-Command { 1..50 | ForEach-Object {
  Invoke-RestMethod -Method Post -Uri "$base/trips" -ContentType "application/json" -Body (@{
    status="scheduled"; origin="O$_"; destination="D$_"
    gps_start_lat = 51.9 + (Get-Random -Maximum 5) / 10
    gps_start_lon = 4.1  + (Get-Random -Maximum 5) / 10
    gps_end_lat   = 52.0 + (Get-Random -Maximum 5) / 10
    gps_end_lon   = 4.3  + (Get-Random -Maximum 5) / 10
    load_weight_kg = 200 + (Get-Random -Maximum 800); vehicle_type="Truck"
  } | ConvertTo-Json) | Out-Null } }
```

Then poll `GET /api/trips?unassigned=true` until empty — all 50 must be
assigned, and total time / 50 is your mean assignment latency (the greedy path
is a single OSRM matrix fetch + in-memory scoring; expect sub-second per trip
with a warm OSRM cache).