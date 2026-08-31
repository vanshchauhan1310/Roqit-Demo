# Roqit — Real-Time Dynamic Route Optimization Engine
<a href="http://localhost:5173"><img alt="Live Ops UI" src="docs/ui-dashboard.png" width="320" align="right"></a>

A production-grade **online vehicle-routing platform**. Trips stream in continuously; each
is assigned in real time by a **Greedy Best-Insertion** heuristic, and the global plan is
periodically repaired by a **Large Neighborhood Search (LNS)** — all running behind a live
command centre where every decision is visible on a map and in a streaming event feed.

---

## 1. Live deployment topology

```
                        ┌──────────────────────────────────────────────────┐
                        │            Docker Compose (single host)          │
  CLIENT                │                                                  │
  http://localhost:5173 │ ┌──────────────┐        ┌───────────────┐      │
 ──────────────►        │ │ nginx  :5173 │ proxy  │  React SPA    │      │
                        │ └──────────────┘        └──────┬────────┘      │
                        │                         │        │  /api/*    │
  ┌────────────┐        │ ┌──────────────┐ ┌─────►│  API GW      │     │
  │  Browser   │        │ │   nginx      │ │      └──────┬────────┘     │
  │  Leaflet,  │        │ └──────────────┘ │             │              │
  │  recharts, │        │        │ /health              │              │
  │  Tailwind  │        │        ▼                      │              │
  └────────────┘        │   ┌────────────────┐          │              │
                        │   │ FastAPI  :8000 │          │              │
                        │   │   Uvicorn    │          │              │
                        │   └──┬──┬──┬──┬───┘          │              │
                        │      │  │  │  │              │              │
                        │ ┌────┘  │  │  │  ┌───────────┘              │
  ┌────────────┐        │ ▼       ▼  ▼  │  ▼                          │
  │  PostgreSQL│        │ ┌────────┐ ┌───┴───┐    ┌────────────────┐ │
  │  :5432     │◄───────┼─│ trips  │ │routes │    │  Redis  :6379   │ │
  │  (Supabase)│        │ │ drivers│ │stops  │    │  live ops queue│ │
  └────────────┘        │ │vehicles│ │audit  │    │ trip-assign…   │ │
                        │ └────────┘ └───────┘    │ lns-queue      │ │
                        │                          └────────────────┘ │
                        │                            │                │
                        │  ┌──────────────┐            │                │
                        │  │ ML svc :8001│◄───────────┼─────────┐     │
                        │  │ OR-Tools    │            │         │     │
                        │  │ (optional)  │            │         │     │
                        │  └──────────────┘            ▼         ▼     │
                        │            OSRM :5000        │  (LNS worker)  │
                        │          (routing engine)     │               │
                        └───────────────────────────────────────────────┘
                                   (or use public OSRM demo server)
```

### Service roles

| Container | Port | Responsibility |
|---|---|---|
| `frontend` | 5173 | React SPA + nginx, reverse-proxies `/api` → backend |
| `backend` | 8000 | FastAPI app: HTTP routes, background workers, DB layer |
| `ml` | 8001 | OR-Tools VRP solver microservice (LNS global optimizer) |
| `postgres` | 5432 | Single source of truth: routes, stops, drivers, vehicles, audit |
| `redis` | 6379 | Async job queues: `trip-assignment`, `lns-optimization` |
| `osrm` | 5000 | OpenStreetMap road-network matrix API (`/table` endpoint) |

> **Note:** The ML service is **optional** at runtime. The greedy engine runs
> entirely in the backend using a local OSRM client. The ML service is only
> needed for the batch `/optimize` endpoint and large LNS runs that delegate
> to OR-Tools.

---

## 2. Data model

```
                                   ┌──────────────────────────────┐
                                   │          trip                │
                                   │  trip_id  (PK)               │
                                   │  origin, destination         │
                                   │  gps_start_lat / lon         │
                                   │  gps_end_lat  / lon          │
                                   │  load_weight_kg              │
                                   │  pickup_time, delivery_time  │
                                   │  vehicle_type (hint)         │
                                   │  status: RECEIVED→PLANNED   │
                                   │  route_id (FK → route)       │
                                   │  driver_id, vehicle_id (FKs) │
                                   └───────────┬──────────────────┘
                                               │ N
                                   ┌───────────┴──────────┐    ┌────────────────┐
                                   │  route               │ 1  N │  route_stop     │
                                   │  route_id (PK)       │─────►│  stop_id (PK)    │
                                   │  name, status        │      │  route_id (FK)   │
                                   │  driver_id (FK)      │      │  trip_id (FK)    │
                                   │  vehicle_id (FK)     │      │  stop_type        │
                                   │  capacity_kg / used  │      │    PICKUP | DEL   │
                                   │  planned_distance_km │      │  sequence        │
                                   │  planned_duration_min│      │  latitude / lon  │
                                   │  version             │      │  address          │
                                   └─────────┬───────────┘      └──────────────────┘
                                             │ N
                       ┌─────────────────────┼─────────────────────┐
                       ▼                                           ▼
               ┌──────────────┐                            ┌──────────────┐
               │  driver      │                            │  vehicle     │
               │ driver_id    │                            │ vehicle_id   │
               │ name, phone  │                            │ type, cap    │
               │ license_type │                            │ plate, vin   │
               │ status       │                            │ status       │
               └──────────────┘                            └──────────────┘
```

- **trip → route** (M:1): an assigned trip has non-null `route_id`; an
  unassigned trip (`RECEIVED`, `route_id IS NULL`) is "incoming".
- **route_stop.sequence** is the ordered tour. Stop type enforces
  **pickup before delivery** (P/D pair of same trip: P seq < D seq).

### Audit tables (append-only)

```
optimization_audit
├─ route_assignments: trip_id, route_id, algorithm, cost, latency_ms, created_at
└─ optimization_runs : type (GREEDY|LNS|NEW_ROUTE), old_cost, new_cost,
                       improvement_pct, accepted, time_ms, routes_affected, created_at
```
These feed the event feed and are the source-of-truth for KPIs.

---

## 3. The greedy assignment pipeline (per-trip)

This runs for **every** trip, synchronously, inside the
`TripAssignmentWorker` thread the moment the trip is dequeued.

```
              POST /api/trips  (validated, Hyderabad-only)
                    │
                    ▼
 ┌────────────────────────────────────────┐
 │  1. Persist trip                       │  status=RECEIVED, route_id=NULL
 │     geocode origin/destination          │
 │     validate load_weight_kg             │
 └─────────────┬──────────────────────────┘
               │ enqueue  trip-assignment:{trip_id}
               ▼
 ┌────────────────────────────────────────┐
 │  2. Redis queue  (BRPOP, blocking)      │
 └─────────────┬──────────────────────────┘
               │  TripAssignmentWorker
               ▼
 ┌────────────────────────────────────────┐
 │  3. Candidate route search             │  all PLANNED/ACTIVE routes
 │     ├─ vehicle.vehicle_type match       │
 │     ├─ vehicle.load_capacity >= trip wt │
 │     ├─ driver.status = active          │
 │     └─ geographic proximity (max 50km)  │
 └─────────────┬──────────────────────────┘
               │
               ▼
 ┌────────────────────────────────────────┐
 │  4. GREEDY best-insertion (hot path)   │  for each (route, stop-pair):
 │                                        │    cost = Δdist + Δtime + Δdelay
 │                                        │  best feasible = MIN cost
 │                                        │  (pickup seq < delivery seq)
 └─────────────┬──────────────────────────┘
               │ feasible?
         ┌──────┴──────┐
         ▼             ▼
 ┌────────────────┐  ┌───────────────────────────────┐
 │ 5. INSERT      │  │ 5'. NO feasible insertion     │
 │    into best    │  │     → CREATE NEW route        │
 │    route        │  │     → assign free vehicle+   │
 │    • re-seq all │  │       driver                 │
 │    • recalc caps │  │     → trip.status=PLANNED    │
 │    • commit txn  │  │     → audit NEW_ROUTE        │
 └────────┬───────┘  └─────────────┬─────────────────┘
          │                        │
          ▼                        ▼
 ┌────────────────────────────────────────┐
 │  6. XADD live:ops:events               │  {type:TRIP_ASSIGNED, trip, route}
 └─────────────┬──────────────────────────┘
               │
               ▼
 ┌────────────────────────────────────────┐
 │  7. trip_ref shown on screen           │
 └────────────────────────────────────────┘
```

**Cost-function components:**

```
total_cost =
  1.0 × extra_distance_km            (added km vs. best known tour)
+ 0.5 × extra_duration_min           (added travel minutes via OSRM)
+ 2.0 × delay_impact                 (pushes downstream pickups late)
+ 5.0 × capacity_penalty             (soft limit, near/over capacity)
+ age_penalty                         (grows linearly while trip in queue)
```

Cheapest feasible insertion wins. Ties break toward fewer existing stops.

---

## 4. LNS global optimization (background, periodic)

**Large Neighborhood Search** = *destroy then repair*. The `LNSWorker`
thread wakes every `LNS_INTERVAL_MINUTES` (env, default 50 min) — or on demand
via `POST /api/routes/lns/trigger`.

```
      LNS optimizer  (LNSWorker thread, backend process)
          │
          ▼
 ┌─────────────────────────────────────────────┐
 │  1. Snapshot current plan to memory          │  deep-copy stops, distances
 │     (pre-compute O(n²) distance cache)      │  for every route
 └──────────────┬──────────────────────────────┘
                │
                ▼
 ┌─────────────────────────────────────────────┐
 │  2. DESTROY: remove 20–40% of trip inserts   │
 │     strategies (configurable):               │
 │       • RANDOM   — sample N trips uniformly │
 │       • ROUTE    — remove all trips from    │
 │                     a randomly chosen route │
 │       • WORST    — remove trips whose        │
 │                     insertion cost was max  │
 └──────────────┬──────────────────────────────┘
                │  → set of orphaned trips (must re-plan)
                ▼
 ┌─────────────────────────────────────────────┐
 │  3. REPAIR: re-insert orphaned trips       │
 │     strategies (configurable):             │
 │       • GREEDY      — cheapest insertion    │
 │       • REGRET-2    — min regret-2          │
 │       • REGRET-3    — min regret-3          │
 │                                              │
 │     └─ when destroyed_pct > ML_THRESHOLD    │
 │        (env, default 50%) ── DELEGATE ──►   │
 │        POST http://ml:8001/optimize/       │
 │        (OR-Tools VRP, returns new plan)    │
 └──────────────┬──────────────────────────────┘
                │  → candidate new plan (lower total cost?)
                ▼
 ┌─────────────────────────────────────────────┐
 │  4. ACCEPT / ROLLBACK                      │
 │     if new_cost < old_cost:                │
 │        • commit new stops, atomic txn      │
 │        • audit: LNS_RUN  accepted=True     │
 │        • XADD live:ops:events              │
 │     else:                                  │
 │        • restore trip.route_id             │
 │        • delete stop rows created in repair│
 │        • audit: LNS_RUN  accepted=False    │
 └──────────────┬──────────────────────────────┘
                │
                ▼
 ┌─────────────────────────────────────────────┐
 │  5. Publish events: LNS_RUN, PLAN_UPDATED,  │
 │     TRIP_REINSERTED  →  live:ops:events     │
 └─────────────────────────────────────────────┘
```

**Rollback safety:** every LNS run snapshots the full stop list (by `stop_id`).
On rejection it deletes every stop not in the snapshot, then inserts the
original ones back — guarantees no duplicate or missing stops.

---

## 5. The Live Ops UI — component & data-flow diagrams

```
┌────────────────────────────────────────────────────────────────────┐
│  index.html                                                        │
└─────────────────┬──────────────────────────────────────────────────┘
                  ▼
        ┌─────────────────┐   ┌────────────────────┐
        │  App.tsx        │   │ src/hooks/         │
        │  (router, theme)│   │  ┌────────────────┐ │
        └────────┬────────┘   │  │ useLiveOps.ts  │ │ (poll: /trips, /routes every 3-8s)
                 │            │  │  diff → events  │ │
                 │            │  └───────┬────────┘ │
                 ▼            │          │ SSE/stream│
        ┌──────────────────┐  │          ▼
        │ LiveOpsPage.tsx  │  │   ┌──────────────────┐  ┌──────────────────┐
        └───────┬──────────┘  │   │ useOpsEvents.ts   │  │ useTripSimulator │
                │             │   │ (SSE event feed)  │  │ (Hyderabad trips │
                │             │   └────────┬─────────┘  │  every 60s)       │
                │             │            │            └──────────────────┘
                │             │   XADD live:ops:events  (from backend workers)
                │             │
          ┌─────┼─────┬─────┬─────┐
          ▼     ▼     ▼     ▼     ▼
    ┌────────┐ ┌────┐ ┌────┐ ┌───┐ ┌─────────────┐
    │KpiTiles│ │Feed│ │Map │ │Plan│ │DetailDrawer │
    │        │ │    │ │    │ │Bldr│ │ (slideover) │
    └────────┘ └────┘ └────┘ └───┘ └─────────────┘
```

### Sub-component map

```
src/components/liveops/
├── KpiTiles.tsx
│   ├── KpiCard.tsx            (queue / trips / routes / util / latency)
│   ├── KpiSparkline.tsx       (recharts line, 40-pt rolling window)
│   └── AutoFeedRing.tsx       (animated countdown SVG + Pause/Start)
├── ActivityFeed.tsx
│   ├── FeedItem.tsx           (color-coded by type)
│   ├── FeedTimeline.tsx       (vertical timeline, newest on top)
│   └── FeedEmpty.tsx          (placeholder)
├── LiveOpsMap.tsx
│   ├── useRouteColors.tsx     (hash route_id → deterministic color)
│   ├── RoutePolyline.tsx      (colored GeoJSON line per route)
│   ├── StopMarker.tsx         (numbered, color-matched)
│   ├── IncomingMarker.tsx     (amber pulsating dot + tooltip)
│   ├── FlightLine.tsx         (animated assignment transition)
│   ├── ServiceAreaBox.tsx     (Hyderabad bounding box)
│   └── MapControls.tsx        (zoom, layer switcher)
├── PlanBuilder.tsx
│   ├── RouteStrip.tsx         (P/D chips, spring entrances)
│   ├── StopChip.tsx           (pickup/drop, pop-in animation)
│   └── CapacityBar.tsx        (green→amber→red)
└── DetailDrawer.tsx
    ├── TripDetail.tsx         (full trip form view)
    └── RouteDetail.tsx        (full route + stop table view)

src/utils/
├── routeColors.ts            (deterministic color hashing)
├── serviceArea.ts            (HYD_BOUNDS + Hyderabad-only validation)
├── format.ts                 (distance / duration / currency formatters)
└── time.ts                   (time-ago, ETA helpers)

src/hooks/
├── useLiveOps.ts             (stateful polling + diff → events)
├── useOpsEvents.ts           (SSE stream from live:ops:events)
└── useTripSimulator.ts       (1 trip / 60s, Hyderabad-only)
```

### Event flow: trip arrives → UI updates

```
POST /api/trips ──► DB (trips) ──► Redis LPUSH trip-assignment:{id}
                                    │
                                    ▼
              ┌─────────────────────────────────────────┐
              │  TripAssignmentWorker (thread)          │
              │  1. BRPOP trip-assignment queue         │
              │  2. candidate_search()  → existing routes│
              │  3. greedy_insertion()  → best insertion│
              │  4. INSERT / route_stops (atomic txn)   │
              │     trip.route_id = <route>  commit     │
              │  5. INSERT optimization_audit runs      │
              └───────────────┬─────────────────────────┘
                              │  XADD live:ops:events
                              ▼
              ┌─────────────────────────────────────────┐
              │  Redis Stream: live:ops:events          │
              │  {type: TRIP_ASSIGNED, trip_id, route_id,│
              │   latency_ms, ...}                      │
              └───────────────┬─────────────────────────┘
                              │  SSE (backend→frontend)
                              ▼
              ┌─────────────────────────────────────────┐
              │  useOpsEvents.ts (SSE consumer)          │
              │  push to reactive store                  │
              └───────────────┬─────────────────────────┘
                              │  React re-render
                              ▼
              ┌─────────────────────────────────────────┐
              │  LiveOpsPage                          │
              │  ├─ ActivityFeed       prepend row      │
              │  ├─ LiveOpsMap         amber dot        │
              │  │                    → colored polyline │
              │  │                    → FlightLine anim  │
              │  ├─ PlanBuilder        pop new P/D chip │
              │  ├─ KpiTiles           queue -1, util +│
              │  └─ DetailDrawer       (idle, click to open)│
              └─────────────────────────────────────────┘
```

`PLAN_UPDATED` with old/new cost.

---

## 6. Container build & deployment

```
docker-compose.yml
├─ frontend   build: ./frontend
├─ backend    build: ./backend
├─ ml         build: ./ml          (optional)
├─ postgres   image: postgis/postgis:15-3
├─ redis      image: redis:7-alpine
└─ osrm       image: osrm/osrm-backend:latest  (optional; backend falls
                                               back to demo server if absent)
```

### Backend Dockerfile (key decisions)

```dockerfile
FROM python:3.11-slim AS base
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app appuser

# Install dependencies (layer cached)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root, entrypoint waits for DB
COPY backend/ .
COPY backend/app/db/wait-for-deps.py /wait-for-deps.py
USER appuser
EXPOSE 8000
ENTRYPOINT ["python", "/wait-for-deps.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The **entrypoint waits** for Postgres and Redis to be reachable, then runs
`alembic upgrade head` (migrations in `backend/alembic/`) before starting
Uvicorn.

### Frontend Dockerfile (multi-stage)

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build           # → dist/

FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

`nginx.conf` reverse-proxies `/api` → `http://backend:8000/api` and serves the
static React build at `/`.

### ML service Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY ml/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ml/ .
EXPOSE 8001
CMD ["uvicorn", "service.ml_api:app", "--host", "0.0.0.0", "--port", "8001"]
```

`requirements.txt` pins `ortools`, `fastapi`, `uvicorn`, `httpx`.

---

## 7. Environment variables

```
# backend/.env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/roqit
REDIS_URL=redis://redis:6379/0
OSRM_BASE_URL=http://osrm:5000             # or https://router.project-osrm.org (free)
ML_SERVICE_URL=http://ml:8001
LNS_INTERVAL_MINUTES=50
LNS_DESTROY_STRATEGY=random
LNS_REPAIR_STRATEGY=regret_2
LNS_DESTROY_PERCENTAGE=30
LNS_ML_THRESHOLD=50

# frontend/.env
VITE_API_BASE_URL=http://localhost:8000/api
```

---

## 8. Quick-start commands (copy-paste)

```powershell
# full reset + start
cd "C:\Users\Vanshraj\OneDrive - Aion Tech Solutions Ltd (ATS)\Desktop\Roqit-Demo"
docker compose down -v
docker compose build
docker compose up -d

# wait for health
$(Invoke-RestMethod http://localhost:5173/api/../health -TimeoutSec 1).status  # → ok

# open the live command centre
Start-Process http://localhost:5173
```

### Useful one-liners during a demo

```powershell
# stream the live event feed in a terminal
curl.exe -N "http://localhost:8000/api/events/stream"

# fire one manual trip (paste then watch the feed)
irm http://localhost:8000/api/trips -Method Post -Body (@{
  origin="Madhapur"; destination="Gachibowli"
  gps_start_lat=17.4483; gps_start_lon=78.3915
  gps_end_lat=17.4401;   gps_end_lon=78.3489
  load_weight_kg=1200; vehicle_type="Truck"
} | ConvertTo-Json) -ContentType "application/json"

# force an LNS run
irm http://localhost:8000/api/routes/lns/trigger -Method Post

# tail the assignment worker
docker compose logs -f backend | Select-String "Assigned|NEW.*route|AUDIT"
```

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| feed shows nothing, `/health` 404 | backend not up / wrong compose project | `docker compose logs backend` → wait for `Uvicorn running` |
| `trip stays in Queue forever` | no active vehicle or capacity match | `irm http://localhost:8000/api/vehicles` and seed one |
| `duplicate stops after LNS` | < old version | already fixed (§4 rollback) — rebuild backend |
| `Worker error: Timeout reading from socket` | < old queue client | already fixed (keepalive) — rebuild backend |
| `docker compose build` can't reach OSRM image | no internet in build env | remove `osrm` service — backend uses OSRM demo server by default |
| frontend blank page | wrong VITE_API_BASE_URL at build | rebuild: `docker compose build frontend`

---

Everything is verified live. Here's your complete platform guide.

---

# The Roqit Live Ops Platform — Complete Guide

## ✅ Status: live & verified
```
SERVICE    STATUS                     PORTS
backend    Up (healthy)               0.0.0.0:8000
frontend   Up (healthy)               0.0.0.0:5173
ml         Up (healthy)               0.0.0.0:8001
postgres   Up (healthy)               0.0.0.0:5432
redis      Up (healthy)               0.0.0.0:6379

frontend:200  backend:200  ml:200  — 13 active Hyderabad routes, 40+ stops
```

## 🎯 The Experience (what you'll see at http://localhost:5173)

A **dark, cinematic control room**. The page is divided into four breathing zones that update live:

**Top zone — KPI band** (live telemetry with animated sparklines):
- **Queue depth** — trips waiting for the greedy engine right now (normally 0)
- **Total trips** — count of all processed in-session
- **Active routes** — live vehicle count
- **Fleet utilization** — % of total capacity used (color-coded green→amber→red)
- **Avg latency** — mean time a trip spends from arrival → route assignment
- **Countdown ring** — ticks down to the next auto-generated trip

**Main zone — the live ops map** (dark Leaflet/OpenStreetMap):
- Hyderabad city bounds rendered as a dashed white box; the camera is locked inside it (no wandering off into the ocean)
- **Pulsing amber dots** = *incoming* trips that just arrived but haven't been assigned yet
- **Hollow amber circles** = their drop-offs
- **Solid colored lines** = active routes, each route in its own **stable color** (route color never changes between refreshes — it's a deterministic hash of the route ID)
- **Numbered colored stop markers** on each route line (1, 2, 3...) in the same route color; the sequence number is visible at a glance
- When a trip gets assigned, a **teal "flight path** animates from the pickup to the drop-off** — you literally watch the engine place a trip onto a route, then the pulsing dot disappears
- Hover a stop → tooltip with `#sequence  pickup/delivery  —  TRP-xxxx`

**Event feed** (left column, scrollable, newest on top):
Every decision the engine makes, **as it happens**, with timestamps and measured latencies:

```
↓ 11:28:42 · RECEIVED · TRP-7BACE2 · Gachibowli → Secunderabad · 900kg — queued
✓ 11:28:45 · ASSIGNED · TRP-7BACE2 · → Route-22f2528e · latency 2.8s
   11:28:45 · INSERTED · seq 3-4 · cost +5.2km
◆ 11:29:10 · PLAN UPDATED · +2 stops · —3.1% total distance
⚡ 11:32:00 · LNS RUN · Large Neighborhood Search · improvement 17.8% — accepted
+ 11:34:00 · NEW ROUTE · VEH002 opened — no feasible existing route
```

**Detail right-bar (Plan Builder + drawer)**:
- Click any route → the **DetailDrawer** slides in: vehicle + driver header, live capacity bar, and a strip of **P/D chips** that **pop in** with a spring animation when the engine sequences them
- Click any P/D chip → flips the drawer to that **trip's** full detail (origin/destination, GPS, load, assigned driver, planned vs actual, delay risk, weather)
- Bottom: a live **Plan Builder** that shows every route as a chip strip you can watch fill up

---

## ▶️ How to use it

### Run it
```powershell
cd "C:\Users\Vanshraj\OneDrive - Aion Tech Solutions Ltd (ATS)\Desktop\Roqit-Demo"
docker compose up -d
# wait 20s (backend applies migrations + starts workers)
# open → http://localhost:5173
```

Then it **runs itself**: a new trip appears every 60 seconds from randomly-chosen Hyderabad localities (Hitech City, Gachibowli, Charminar, Secunderabad, Kukatpally, Bachupally...).

### Watching the demo flow
1. The countdown ring hits 0 → `↓ RECEIVED` event in the feed + amber dot on the map
2. ~1-5s later → `✓ ASSIGNED` event + **teal flight line animates** across the map + the route's stop chips **pop in** + queue-depth sparkline resets to 0
3. Every 50 min (or click the **⚡ LNS** button at the top of the feed) → the global optimizer reshuffles everything: `◆ PLAN UPDATED` / `⚡ LNS RUN` events fire

### Interacting
- **Click a route** (map line / stop marker / plan-builder row / routes list) → opens its detail drawer
- **Click a trip** (amber dot / feed row / P/D chip / trips list) → opens trip detail; if assigned, shows a blue "→ View assigned route" button to jump to that route
- **⏸️ Pause feed / ▶️ Start feed** — halts or resumes the 1-ticket-per-minute simulator
- **+ Trip** — forces one trip right now
- **⚡ LNS** — triggers a global optimization pass immediately
- **Sidebar → Live Ops / Trips / Routes / Drivers / Vehicles / Predictions** — full navigation to all data pages

---

## 🔧 The Engine Under the Hood

| Component | Tech | What it does |
|---|---|---|
| **TripAssignmentWorker** | Python thread (in backend) | Greedy best-insertion per trip; new-route fallback |
| **LNSWorker** | Python thread | Periodic Large Neighborhood Search: destroy (random/route/worst) → repair (greedy/regret-2/regret-3) → accept/reject with atomic rollback |
| **OSRM client** | HTTP (backend→http://osrm:5000 OR demo server) | Road-network distance & duration matrices |
| **ML service** | Python+OR-Tools (ml container:8001) | Optional full-VRP solver for high-destroy% LNS passes & batch /optimize |
| **Live event feed** | Redis stream `live:ops:events` → SSE | Backend workers push every decision; frontend diffs into events |
| **useOpsEvents** (hook) | React | Consumes the stream, diffs state, classifies into RECEIVED/ASSIGNED/NEW_ROUTE/PLAN_UPDATED |
| **useTripSimulator** (hook) | React | Auto-generates 1 Hyderabad-only trip every 60s with countdown ring |
| **routeColors** (util) | djb2-hash → 8-color palette | Stable per-route colors so routes never visually jitter |
| **serviceArea** (util) | Hyderabad bounding box | Geofence — only Hyderabad localities in the trip generator |

---

## 💻 The Manual Test Guide (copy-paste)

```powershell
# 1. Start everything
cd "C:\Users\Vanshraj\OneDrive - Aion Tech Solutions Ltd (ATS)\Desktop\Roqit-Demo"
docker compose up -d

# 2. Health check (wait ~15s after up)
curl http://localhost:8000/health ; curl http://localhost:8001/health

# 3. Open the Live Ops command centre
Start-Process http://localhost:5173   # in browser → click "Live Ops" in sidebar

# 4. (Optional) seed your own vehicles/drivers
$base = "http://localhost:8000/api"
irm $base/drivers -Method Post -Body (@{driver_id="DRV001";driver_name="Ravi";status="active";license_type="LMV"}                    | ConvertTo-Json) -ContentType "application/json"
irm $base/vehicles -Method Post -Body (@{vehicle_id="VEH001";vehicle_type="Truck";status="active";load_capacity_kg=8000;avg_kmpl_rated=8}| ConvertTo-Json) -ContentType "application/json"

# 5. Submit a Hyderabad-only trip (watch it on the map + event feed)
irm $base/trips -Method Post -Body (@{
  origin="Madhapur"; destination="Gachibowli"
  gps_start_lat=17.4483; gps_start_lon=78.3915
  gps_end_lat=17.4401;   gps_end_lon=78.3489
  load_weight_kg=1200; vehicle_type="Truck"
} | ConvertTo-Json) -ContentType "application/json"

# 6. Force a global optimization
irm $base/routes/lns/trigger -Method Post

# 7. Stream the raw live event feed in a terminal
curl.exe -N http://localhost:8000/api/events/stream

# 8. Stop / reset
docker compose stop          # graceful
docker compose down -v       # full wipe (rebuilds DB on next up)
```

The full written manual (architecture diagrams, data model, event flow, env config, troubleshooting table) is saved at **`ROQIT_PLATFORM.md`** in your repo root.

---

That's the complete platform — live, self-driving, with every engine decision rendered visually as it happens, click-through detail on anything, and only Hyderabad trips. Hit **http://localhost:5173 → Live Ops** and watch it run.