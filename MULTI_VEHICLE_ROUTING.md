# Multi-Vehicle Routing with Hub Start/End Points

> **Status: solver + API implemented; frontend and hub data model not yet.** The multi-vehicle
> assignment engine (`ml/src/optimizer/fleet.py`), its ML-service endpoint
> (`POST /optimize/fleet`), and the backend endpoint (`POST /api/routes/optimize-fleet`) are
> built and tested — see [§10](#10-implementation-status). The existing single-vehicle path is
> untouched and remains the one the Create Route wizard uses. See [README.md](./README.md) for
> the platform overview and [WEIGHT_AWARE_ROUTING.md](./WEIGHT_AWARE_ROUTING.md) for the
> single-vehicle multi-objective cost model.

## 1. What exists today vs. what's being asked for

Confirmed by direct code inspection (repeated here since it's the entire premise of this doc):

- `backend/app/services/route_optimizer.py::optimize_route()` takes exactly one
  `vehicle_capacity_kg`, one `avg_kmpl_rated`, one `fuel_price_per_l` per call - one vehicle's
  parameters, not a fleet.
- `backend/app/schemas/optimize.py::OptimizeRouteRequest`/`OptimizeRouteResponse` model one route:
  a single flat `order: list[str]` of stop keys, not a set of per-vehicle routes.
- `ml/src/optimizer/opt.py::solve()` and `ml/src/optimizer/hybrid_solver.py::hybrid_solve()` both
  return one `SolveResult` containing exactly one `route: list[int]`.
- There is **no depot concept anywhere**, not even an implicit pinned first stop -
  `construct_greedy()` starts from whichever job happens to be first in the input list.
- `backend/app/models/vehicle.py:23` - `base_location: Mapped[str | None] = mapped_column(String)`
  - a free-text city name, **not** a coordinate. Nothing in the codebase geocodes it or uses it
  for routing; it's fetched only for display in the roster UI.
- Grepping `backend/` and `ml/` for `depot|multi.?vehicle|multi.?depot|fleet_size|num_depots`
  returns zero matches.

What's being asked for - allocate a pool of trips across **multiple** vehicles, each starting and
ending at a **hub**, producing the most efficient combination of routes - is the textbook
Capacitated Vehicle Routing Problem with Pickup and Delivery (and, once a hub is fixed per
vehicle, effectively PDPTW's depot-constrained sibling). This is not a bigger version of what
exists; it's a different problem that happens to reuse pieces of the existing one.

## 2. Hub/depot data model

`base_location` cannot be used as-is - OSRM and the solver both need real coordinates, and
geocoding a city-name string live on every optimize call is unreliable (rate-limited, and the
"hub" is a fixed operational fact that shouldn't depend on a third-party geocoder being up) and
wasteful (the same string would be re-geocoded on every request).

**Two options, in order of recommendation:**

1. **A shared `Hub` table** - `hub_id`, `name`, `latitude`, `longitude`, plus a `hub_id` FK on
   `Vehicle` (nullable, defaulting to unset for existing vehicles). Multiple vehicles plausibly
   share one depot, so this avoids duplicating coordinates per vehicle and gives dispatchers a
   real place to manage "where do our vehicles start from" independent of any one vehicle record.
2. **`hub_lat`/`hub_lon` columns directly on `Vehicle`** - simpler migration, but duplicates
   coordinates across every vehicle based at the same physical depot, and offers no natural place
   to rename/manage a depot as its own entity.

Recommend (1). Either way, this is a real schema migration (new table or new columns) - not
something a geocode-on-the-fly workaround should stand in for.

## 3. API/schema shape change

`OptimizeRouteRequest`/`OptimizeRouteResponse` model exactly one vehicle and one route today. A
multi-vehicle version needs to model a *pool*:

```text
MultiVehicleOptimizeRequest
    vehicles: [{ vehicle_id, capacity_kg, avg_kmpl_rated, hub_id }, ...]
    trips: [ ...same OptimizeStopInput shape as today... ]

MultiVehicleOptimizeResponse
    routes: [{ vehicle_id, order: [...], total_duration_seconds, total_distance_meters }, ...]
    unassigned_trip_ids: [...]   # trips that couldn't fit any vehicle - see §6
```

This is a genuinely new, additive endpoint (`/routes/optimize-multi` or similar) rather than a
backward-compatible extension of `/routes/optimize` - the single-vehicle endpoint should keep
working unchanged for the existing Create Route flow (see §7).

## 4. Solver architecture: two real options

**Option A - cluster-first-route-second (recommended starting point).** Partition trips across
vehicles with a cheap heuristic (e.g. nearest-hub assignment, or a k-means-style spatial cluster
per vehicle weighted by remaining capacity), then run today's existing `opt.solve()` /
`hybrid_solve()` **unchanged** on each vehicle's assigned trip subset, with the hub injected as a
pinned start/end node (see §5). This reuses the already-verified single-vehicle solver as a
subroutine rather than requiring a new solver core - the multi-vehicle logic lives entirely in the
clustering step, which is simpler to build, test, and reason about independently.

**Option B - true joint multi-vehicle ALNS.** A single destroy/repair search where a "repair" move
can insert a removed job into *any* vehicle's route, not just the one it was destroyed from. This
is the academically "better" approach (it can escape bad initial clusters that Option A's static
partition can't) but requires reworking `opt.py`'s core loop - `_destroy`/`_repair` currently
operate on one route; a joint version needs to track N routes and evaluate insertion cost across
all of them per job, which is a materially larger algorithmic change.

**Recommendation: build Option A first.** It's incremental on top of already-working code, testable
per-vehicle using the existing single-vehicle test surface, and gets a usable multi-vehicle feature
shipped faster. Option B is worth revisiting later specifically if Option A's cluster quality proves
inadequate in practice (e.g. consistently poor allocation near cluster boundaries) - not a
prerequisite for a first version.

## 5. The hub as a pinned node

Neither `opt.py` nor `hybrid_solver.py` has any concept of a node that must stay at a fixed
position. Adding one means:

- Injecting the hub's coordinates as index `0` in the coordinate/duration/distance matrices for
  each vehicle's sub-problem, and (if a return-to-hub leg is required) a mirrored copy at the last
  index.
- `construct_greedy()`, `_destroy()`, `_repair()`, and `best_pair_insertion()` all need to treat
  index `0` (and the mirrored end index, if used) as never removable and never a valid insertion
  position for any other job - today nothing in the LNS destroy/repair logic protects any
  particular index from being touched.
- `route_is_feasible()`'s duplicate-stop check and precedence check are unaffected (the hub isn't
  a job's pickup/delivery), but capacity checking should start counting from `0` at the hub, which
  `_load_at_positions()` already does implicitly as long as the hub itself carries no `Job` weight
  delta - no change needed there beyond ensuring the hub is never mistaken for a real stop.

## 6. What happens when no allocation fits

Once real infeasibility becomes reachable (see the audit's finding that today's single-vehicle
system can't actually produce an infeasible instance once Filter & Validate has run - multi-vehicle
allocation reintroduces this risk, since a trip might not fit **any** vehicle in the pool even
though each vehicle individually has capacity for *some* trips), the response needs an explicit
`unassigned_trip_ids` list rather than a hard failure - a dispatcher should see "23 of 25 trips
assigned across 4 routes, these 2 didn't fit" rather than the whole request failing. This directly
depends on the audit's Implement-Now item (a typed infeasible/partial response, not an unhandled
assertion) already being in place before this feature is attempted.

## 7. UI changes needed

- **Vehicle step** becomes a fleet multi-select (checkbox list) instead of the current single-pick
  radio-style list - `VehicleStep` in `CreateRouteModal.tsx` would need a genuinely different mode,
  not a tweak.
- **Driver assignment** becomes per-vehicle, not once for the whole route group - likely a second
  pass after vehicles are chosen, pairing each selected vehicle with a driver.
- **Filter & Validate / capacity** need to consider the whole vehicle pool's *combined* capacity
  for the "is this trip eligible at all" pre-check, not one vehicle's - a trip too heavy for every
  vehicle in the pool is truly ineligible; a trip that fits some vehicles in the pool but not others
  is eligible, just constrained in which vehicle it can end up on.
- **Review** needs to render N routes (one map/summary per vehicle) instead of one, plus the
  unassigned-trips list from §6 if non-empty.

## 8. Recommendation: a separate flow, not a replacement

The audit found this app's actual current usage is small, manually-curated trip groups on one
vehicle - not fleet-wide dispatch. Multi-vehicle/hub routing should ship as a **distinct entry
point** (e.g. "Create Multi-Route Plan," a new page/modal) rather than folding into the existing
`CreateRouteModal` wizard. Reasons:

- The existing wizard's step-by-step, single-vehicle mental model (Driver → Vehicle → Filter &
  Validate → Trips → Review) doesn't extend cleanly to "pick a fleet, then see N routes" - trying
  to make one wizard serve both would compromise the simple case for the sake of the complex one.
- It keeps the existing, already-verified single-vehicle path (and everything in
  `WEIGHT_AWARE_ROUTING.md`) completely unaffected - the new endpoint and new UI are additive, not
  a modification of working code.
- It lets the two features ship and be tested independently, on their own timelines.

## 9. Rough effort shape (not a committed plan)

For calibration only - not file-by-file, since nothing here is scheduled for implementation:

| Layer | Scope |
|---|---|
| Schema/migration | New `Hub` table + FK on `Vehicle` |
| Backend | New multi-vehicle optimize endpoint + request/response schemas; clustering step (Option A) |
| Optimizer | Pinned hub-node support in `opt.py`'s construction/destroy/repair; per-vehicle `solve()` calls reused as-is |
| API error handling | Typed partial/unassigned-trips response (depends on the audit's infeasibility-handling item already landing) |
| Frontend | New page/flow: fleet multi-select, per-vehicle driver assignment, multi-route review/map |

This is a multi-week effort spanning every layer of the stack, not a follow-on to the button-merge
work in this same session - treat it as its own initiative with its own plan when it's actually
prioritized.

## 10. Implementation status

### Built and tested

| Component | Where | Notes |
|---|---|---|
| Multi-vehicle solver | `ml/src/optimizer/fleet.py` | Greedy cheapest-insertion across the fleet, then LNS whose repair step can move a job to **any** vehicle - a genuine joint search, not N independent solves. Chose Option B's inter-vehicle moves over Option A's static clustering after all, because reusing `opt.best_pair_insertion`'s primitives made it no harder to build. |
| Hard constraints | reused from `opt.py` | `route_is_feasible` (precedence + capacity-at-every-stop) is called unchanged, before any cost is computed. An infeasible candidate is discarded, never scored. |
| Cost objective | `fleet.evaluate_route` | Cost-denominated: fuel (load-derated km/l) + driver-time + per-km operating + per-vehicle fixed cost. Falls back to a duration proxy when no rates are supplied, flagged via `cost_is_monetary` so callers never render a proxy as currency. |
| Depot / hub legs | `FleetVehicle.start_idx` / `end_idx` | Optional node indices into the same matrices. Depot stops are kept **out** of the job route and added only when computing metrics, which sidesteps the duplicate-stop check when start and end are the same hub. |
| ML endpoint | `POST /optimize/fleet` | Typed `status`: `SUCCESS` / `PARTIAL` / `NO_FEASIBLE_SOLUTION`. Job-count cap (`MAX_FLEET_JOBS = 60`). |
| Backend endpoint | `POST /api/routes/optimize-fleet` | Additive; `POST /api/routes/optimize` is unchanged. |
| Unknown-weight guard | `route_optimizer._unweighed_trip_ids` | A capacity-constrained dispatch containing a trip with `load_weight_kg = None` returns `MISSING_REQUIRED_DATA` **before** any OSRM or ML call. `0.0` is treated as a real recorded weight, never conflated with unknown. |
| Tests | `ml/tests/test_fleet.py` | 9 tests, runnable via `python tests/test_fleet.py` or pytest. Covers sequential-vs-concurrent capacity, oversized jobs, fixed-cost consolidation, depot legs, load-dependent fuel, and precedence/capacity invariants. |

### Not built

- **Hub coordinates.** `Vehicle.base_location` is still a free-text city string. `start_idx`/`end_idx` exist in the solver but nothing populates them yet - the `Hub` table from [§2](#2-hubdepot-data-model) is still the prerequisite.
- **Frontend.** No multi-vehicle UI. The Create Route wizard still uses the single-vehicle endpoint.
- **Cost rates.** `driver_cost_per_hour` / `operating_cost_per_km` are accepted as request parameters but have no schema home; callers must supply them per-request. `vehicle_intelligence_service.py` computes a *retrospective* `fleet_avg_cost_per_km` from completed trips, which is a plausible calibration source but is not wired in.
- **Traffic, road type, forecast weather, driver shifts, cargo compatibility.** No data source exists for any of these. `fleet.LegDurationFactor` is the neutral-by-default hook where a traffic/weather/road model plugs in later; a factor of 1.0 means "no adjustment applied", **not** "no traffic".
