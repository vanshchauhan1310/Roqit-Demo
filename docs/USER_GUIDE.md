# Roqit — Real-Time Dynamic Route Optimization & Trip Assignment
## User Guide (Live Ops mission-control)

This is your command centre. Vehicles, drivers and trips live in a real
PostgreSQL database; every decision is made by the **greedy best-insertion**
engine (with **LNS** global improvement) running in FastAPI background workers,
and the ML service scores predictions. The page polls the live data every few
seconds, so it always reflects reality.

---

## 1. Starting the platform

### One command (recommended)

```powershell
cd "C:\Users\Vanshraj\OneDrive - Aion Tech Solutions Ltd (ATS)\Desktop\Roqit-Demo"
docker compose up -d          # builds nothing if images exist
docker compose ps             # all 5 services → "healthy"
```

Open **http://localhost:5173** → click **Live Ops** in the sidebar.

> If you just edited code, rebuild the affected service:
> `docker compose build frontend && docker compose up -d frontend`

### Running locally (without Docker)

Requires PostgreSQL, Redis, and Python 3.11 (use the `backend/venv` and
`ml/venv` virtualenvs). Seed data, then:

```powershell
cd backend; .venv\Scripts\activate; python -m uvicorn app.main:app --port 8000
# separate terminal
cd ml;   venv\Scripts\activate;  python -m uvicorn service.ml_api:app --port 8001
# frontend
cd frontend; npm install; npm run dev
```

---

## 2. The Live Ops screen at a glance

```
┌──────────────────────────┬───────────────────────────────┐
│  COMMAND BAR            │  ROQIT LIVE OPS  ·  Hyderabad  │
│  (clock + telemetry)   │  live · auto-refresh           │
├──────── KPI BAND ────────┤                                 │
│  Queue  Trips  Routes   │  ┌───────┐ Queue depth         │
│  Util  Avg latency  🔁 │  │sparkline│ 23 waiting          │
│                         │  └───────┘                     │
├──────── EVENT FEED ──────┼──┬───────────────────────────┤
│  ↓ RECEIVED  TRP-X…     │  │  MAP                         │
│  ✓ ASSIGNED  …3.2s      │  │  amber pulsing dots =       │
│  + NEW ROUTE VEH002      │  │  incoming trips             │
│  ⚡ LNS …                  │  │  colored polylines per     │
│  ◆ PLAN UPDATED +2 stops │  │  route                       │
└──────── EVENT FEED ──────┴──┤  teal flight lines when     │
                             │  a trip is assigned          │
┌──────── PLAN BUILDER ──────┤  click anything for detail  │
│  Route-7BAC  P D P D P D   │  ────────────────────────┐  │
│  Route-9C2D  P D P D       │                          │  │
│  (chips pop in live!)      │                          ▼  │
└───────────────────────────┴──────────────────────── DETAIL │
                                                (slide-over)
```

* **KPI band** — live numbers + sparklines (last 40 samples) for queue depth,
  total trips, active routes, fleet capacity utilization, and average assignment
  latency. The rightmost tile is the **auto-feed** controller: a countdown ring
  that ticks down to the next auto-generated trip.
* **Event feed** — every engine decision appears here as a color-coded,
  time-stamped row. Scroll it like a log; click any row to open that trip/route.
* **Map** — dark control-room styled, Hyderabad bounds shown as a dashed box.
  Incoming trips pulse amber; assigned stops are numbered. Routes each get a
  **stable, deterministic color** (a given route is always the same color).
* **Plan builder** — one strip per route; each stop is a **P** (pickup) / **D**
  (drop) chip that **pops in** when the engine sequences it. A live capacity
  bar shows load progress.
* **Detail drawer** — slides in from the right when you click anything.

---

## 3. Watching a trip do its whole life‑cycle (the demo)

1. Make sure **Auto feed** is **Start** (it is by default). The countdown ring
   begins.
2. When it hits 0 a new trip **spawns** in Hyderabad:
   the feed prints `↓ RECEIVED · TRP-… Hitech City → Secunderabad · 920 kg — queued`,
   and an amber dot appears on the map.
3. Within ~1-5 s the greedy engine inserts it:
   `✓ ASSIGNED · TRP-… inserted into Route-… · queue latency 2.1s`, and a
   **teal flight line** animates from the pickup to the route. The trip
   **disappears** from "Queue"; the route's plan-builder chips pop in.
4. Watch the **sparklines tick** and the **fleet-utilization** number climb.
5. Press **⚡ LNS** (or wait 10 min for the automatic run). The feed prints
   `⚡ LNS OPTIMIZATION · Large Neighborhood Search dispatched`, and after the
   reoptimization you may see `◆ PLAN UPDATED` rows as routes are reshuffled.

---

## 4. Interacting with the platform

### Clicking a trip
| Where | Result |
|---|---|
| An **Incoming Trips** row, the amber map marker, or the drop-off circle | Opens the **Trip Detail** drawer with origin/destination, GPS coords, load, assigned vehicle/driver, planned vs actual distance, pickup/delivery times, delay, traffic, weather, and — if already assigned — a blue **"View assigned route →"** button that flips the drawer to that route |
| An **In Process** trip row | Opens the Trip Detail drawer directly |

### Clicking a route
| Where | Result |
|---|---|
| A **route** row, its map polyline, any numbered stop marker, or the plan-builder strip | Opens the **Route Detail** drawer: vehicle + driver, capacity bar, creation time, and a sortable **stop sequence** table. Each stop chip is clickable → jumps to that trip's detail. |

### The buttons in the KPI feed tile
* **Pause / Start feed** — toggles the 1 trip/minute auto-generator.
* **+ Trip** — fires one trip immediately (handy to speed up a demo).
* **⚡ LNS** — dispatches a real Large Neighborhood Search against the live plan.

### Sidebar navigation
* **Dashboard** — high-level KPI cards.
* **Trips** — paginated, filterable table of every trip.
* **Routes** — list + detail pages for every route.
* **Drivers / Vehicles** — fleet master-data pages.
* **Predictions** — use the ML service directly (pickup/delivery time,
  delay risk, fuel cost).
* **Live Ops** — the mission-control screen documented here.

---

## 5. Creating your own trip (outside the auto feed)

From any REST client:

```powershell
$base = "http://localhost:8000/api"
Invoke-RestMethod -Method Post -Uri "$base/trips" -ContentType "application/json" -Body (@{
  origin = "Madhapur"; destination = "Gachibowli"
  gps_start_lat = 17.4483; gps_start_lon = 78.3915
  gps_end_lat   = 17.4401; gps_end_lon   = 78.3489
  load_weight_kg = 1200; vehicle_type = "Truck"
} | ConvertTo-Json)
```

Return: `202 — {"trip_ref":"TRP-XXXXXXXX","status":"RECEIVED"}`. The trip appears in
the Incoming strip within seconds and is assigned by the engine automatically.

#### Seeded demo accounts
The fresh Docker DB seeds a handful of Hyderabad drivers and 8-tonne trucks.
To add a specific one:

```powershell
Invoke-RestMethod -Method Post -Uri "$base/drivers" -Body (@{
  driver_id="DRV001"; driver_name="Ravi Kumar"; status="active";
  license_type="LMV"; experience_years=5; rating=4.5
  } | ConvertTo-Json) -ContentType "application/json"

Invoke-RestMethod -Method Post -Uri "$base/vehicles" -Body (@{
  vehicle_id="VEH001"; vehicle_type="Truck"; status="active";
  load_capacity_kg=8000; avg_kmpl_rated=8.0
  } | ConvertTo-Json) -ContentType "application/json"
```

---

## 6. Reading the telemetry

* **Queue depth** — trips returned by the API with no `route_id`. The engine
  processes these immediately; the number is normally 0.
* **Avg assignment latency** — measured from the moment a trip is first seen
  unassigned until it gets a `route_id`. Reflects greedy solver + OSRM latency.
* **Fleet utilization** — `sum(used_capacity) / sum(capacity)` across active routes.
* **Color legend** — each route keeps a fixed color for the session; matching
  dots appear in the map tooltip, the plan-builder strip, and the route list.

---

## 7. Stopping / troubleshooting

```powershell
docker compose stop        # graceful stop, data preserved
docker compose start       # resume
docker compose down -v     # full reset (wipes DB + Redis)
docker compose logs -f     # stream all logs live
```

| Symptom | Fix |
|---|---|
| Map shows but `/api` requests 404 | backend container not healthy yet — `docker compose ps` |
| feed doesn’t move | click **+ Trip** to confirm the API works; check `docker compose logs backend` |
| `⚡ LNS` stays "LNS…" | LNS takes 6-10s; the badge resets automatically |
| colors look washed out | the dark-map filter inverts OSM; reload the page |
| Docker daemon won’t start | restart **Docker Desktop** (system tray), wait, then `docker compose up -d` |