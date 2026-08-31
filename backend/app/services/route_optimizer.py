import httpx
from math import isclose
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.optimize import (
    FleetRouteMetrics,
    FleetVehicleRouteOut,
    FleetVehicleSelection,
    OptimizeFleetResponse,
    OptimizeRouteResponse,
    OptimizeStopInput,
)
from app.models.driver import Driver
from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.route import Route
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.services import ml_client
from app.services.dispatch_config_service import (
    ResolvedVehicleConfig,
    ensure_driver_cost_configuration,
    resolve_driver_cost_per_hour,
    resolve_vehicle_config,
)


async def _fetch_matrices(
    points: list[tuple[float, float]],
) -> tuple[list[list[float]], list[list[float]]]:
    """One OSRM /table call for every node in the request - stops, plus any hub
    nodes appended after them. Called once per optimize request, never inside the
    solver's search loop."""
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    url = f"{settings.OSRM_BASE_URL}/table/v1/driving/{coords}?annotations=duration,distance"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Routing provider returned {response.status_code}")

    data = response.json()
    durations = data.get("durations")
    distances = data.get("distances")
    if not durations or not distances:
        raise HTTPException(status_code=502, detail="Routing provider returned no matrix")

    return durations, distances


def _build_jobs(stops: list[OptimizeStopInput]) -> list[dict]:
    """Groups stops by trip_id into pickup-delivery job pairs the ML
    service's hybrid solver operates on. Every trip present must have both
    a pickup and a delivery stop in the request."""
    by_trip: dict[str, dict[str, int]] = {}
    for i, stop in enumerate(stops):
        by_trip.setdefault(stop.trip_id, {})[stop.stop_type] = i

    jobs = []
    for trip_id, indices in by_trip.items():
        if "pickup" not in indices or "delivery" not in indices:
            raise HTTPException(status_code=400, detail=f"Trip {trip_id} is missing its pickup or delivery stop")
        pickup_stop = stops[indices["pickup"]]
        if (
            pickup_stop.assigned_weight_kg is not None
            and pickup_stop.load_weight_kg is not None
            and abs(pickup_stop.assigned_weight_kg - pickup_stop.load_weight_kg) > 1e-6
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Trip {trip_id} has conflicting assigned and load weights",
            )
        jobs.append(
            {
                "trip_id": trip_id,
                "pickup_stop_index": indices["pickup"],
                "delivery_stop_index": indices["delivery"],
                "load_weight_kg": (
                    pickup_stop.assigned_weight_kg
                    if pickup_stop.assigned_weight_kg is not None
                    else pickup_stop.load_weight_kg
                ) or 0.0,
                "parent_trip_id": pickup_stop.parent_trip_id,
                "original_load_weight_kg": pickup_stop.original_load_weight_kg,
                "allowed_vehicle_ids": pickup_stop.allowed_vehicle_ids,
                "allow_split_loads": pickup_stop.allow_split_loads,
            }
        )
    _validate_split_reconciliation(jobs)
    return jobs


def _validate_split_reconciliation(jobs: list[dict]) -> None:
    """Reject malformed split requests before any routing/cost work starts.

    A part's weight is an assignment amount; it must sum exactly to its parent
    trip's recorded original weight. This protects against cargo being silently
    created, lost, or substituted by a lower load during optimization.
    """
    grouped: dict[str, list[dict]] = {}
    for job in jobs:
        parent = job.get("parent_trip_id")
        if parent:
            grouped.setdefault(parent, []).append(job)

    for parent, parts in grouped.items():
        if not all(part["allow_split_loads"] for part in parts):
            raise HTTPException(status_code=400, detail=f"Trip {parent} does not allow split loads")
        originals = {part.get("original_load_weight_kg") for part in parts}
        if len(originals) != 1 or None in originals:
            raise HTTPException(status_code=400, detail=f"Split {parent} is missing a consistent original weight")
        if any(part["load_weight_kg"] < 0 for part in parts):
            raise HTTPException(status_code=400, detail=f"Split {parent} has a negative assigned weight")
        original = float(next(iter(originals)))
        assigned = sum(float(part["load_weight_kg"]) for part in parts)
        if abs(assigned - original) > 1e-6:
            raise HTTPException(
                status_code=400,
                detail=f"Split {parent} does not reconcile: assigned {assigned:g} kg, original {original:g} kg",
            )


async def optimize_route(
    stops: list[OptimizeStopInput],
    vehicle_capacity_kg: float | None = None,
    avg_kmpl_rated: float | None = None,
    fuel_price_per_l: float | None = None,
) -> OptimizeRouteResponse:
    """Fetches a real OSRM duration/distance matrix, groups stops into
    pickup-delivery jobs, and delegates the actual combinatorial search to
    the ML service's hybrid pickup-delivery optimizer (see
    ml/src/optimizer/) - this module only owns the real-world I/O (OSRM),
    matching the rest of this app's backend-never-does-ML-itself convention.

    This is a multi-objective route optimization - distance, time, fuel cost, and cargo/load
    impact (ton-km) are all evaluated together for the same candidate route, then combined into
    one normalized objective (see ml/src/optimizer/opt.py::compute_baselines and
    WEIGHT_AWARE_ROUTING.md) rather than picking "the weight-aware objective" vs. "the plain
    objective" as an all-or-nothing switch. alpha (duration) and delta (distance) are always on -
    both are known from the OSRM matrix regardless of load/vehicle data. gamma (ton-km) turns on
    automatically once any job actually has a load_weight_kg (_build_jobs already defaults missing
    weight to 0.0 per job, so trips with no weight simply don't move that term). beta (fuel cost)
    only turns on when the vehicle's mileage AND a fuel price are both known, since fuel cost is
    meaningless without them. A route where nothing has weight and no vehicle is chosen yet still
    optimizes on distance+time - never falls back to duration alone."""
    if len(stops) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 stops to optimize")

    durations, distances = await _fetch_matrices([(s.latitude, s.longitude) for s in stops])
    jobs = _build_jobs(stops)
    coordinates = [[s.latitude, s.longitude] for s in stops]

    # Internal business-priority weights - deliberately not exposed to the dispatcher (see
    # WEIGHT_AWARE_ROUTING.md). Each term is baseline-normalized before these are applied (see
    # opt.compute_baselines), so these are genuine relative-importance percentages, not raw
    # seconds/meters/currency/tonne-km mixed together.
    alpha = 0.20  # time
    delta = 0.25  # distance
    gamma = 0.15 if any(job["load_weight_kg"] for job in jobs) else 0.0  # cargo/load impact
    beta = 0.40 if (avg_kmpl_rated and fuel_price_per_l) else 0.0  # fuel cost

    try:
        result = await ml_client.optimize_pickup_delivery_route(
            {
                "jobs": jobs,
                "duration_matrix": durations,
                "distance_matrix": distances,
                "coordinates": coordinates,
                "vehicle_capacity_kg": vehicle_capacity_kg,
                "alpha": alpha,
                "beta": beta,
                "gamma": gamma,
                "delta": delta,
                "avg_kmpl_rated": avg_kmpl_rated,
                "fuel_price_per_l": fuel_price_per_l,
            }
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Optimization service error: {exc.response.status_code} {exc.response.text}"
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Optimization service unavailable: {exc}")

    order_indices: list[int] = result["order"]
    return OptimizeRouteResponse(
        order=[stops[i].key for i in order_indices],
        total_duration_seconds=result["total_duration_seconds"],
        total_distance_meters=result["total_distance_meters"],
        solver_used=result["solver_used"],
    )


def _unweighed_trip_ids(stops: list[OptimizeStopInput]) -> list[str]:
    """Trips whose pickup carries no recorded weight. Deliberately distinguishes
    'unknown' from 0 kg: a stop with load_weight_kg=None is unmeasured cargo,
    while 0.0 is a real, recorded empty load. Collapsing the two is what lets an
    over-capacity route pass a capacity check silently."""
    return sorted(
        {s.trip_id for s in stops if s.stop_type == "pickup" and s.load_weight_kg is None}
    )


def _empty_metrics() -> FleetRouteMetrics:
    return FleetRouteMetrics(
        distance_meters=0, duration_seconds=0, fuel_liters=0, fuel_cost=0,
        driver_cost=0, operating_cost=0, fixed_cost=0, peak_load_kg=0,
        total_cost=0, cost_is_monetary=False,
    )


def _refusal(status: str, jobs: list[dict], warnings: list[str]) -> OptimizeFleetResponse:
    """A typed business refusal - HTTP 200 with an explicit status, never a 5xx."""
    return OptimizeFleetResponse(
        status=status,
        routes=[],
        unassigned_trip_ids=[j["trip_id"] for j in jobs],
        totals=_empty_metrics(),
        vehicles_used=0,
        explanation=[],
        warnings=warnings,
    )


def build_hub_nodes(
    stops: list[OptimizeStopInput], configs: list[ResolvedVehicleConfig]
) -> tuple[list[tuple[float, float]], dict[str, tuple[int | None, int | None]]]:
    """Appends each distinct hub's coordinates AFTER the stop coordinates, so the
    stop indices the jobs reference are never disturbed, and returns each
    vehicle's (start_idx, end_idx) into the resulting matrices.

    Pure function - no DB, no network - so the index arithmetic is unit-testable
    on its own.
    """
    points: list[tuple[float, float]] = [(s.latitude, s.longitude) for s in stops]
    hub_index: dict[str, int] = {}
    per_vehicle: dict[str, tuple[int | None, int | None]] = {}

    for cfg in configs:
        idxs: list[int | None] = []
        for hub in (cfg.start_hub, cfg.end_hub):
            if hub is None:
                idxs.append(None)
                continue
            key = str(hub.hub_id)
            if key not in hub_index:
                hub_index[key] = len(points)
                points.append((hub.latitude, hub.longitude))
            idxs.append(hub_index[key])
        per_vehicle[cfg.vehicle_id] = (idxs[0], idxs[1])

    return points, per_vehicle


async def optimize_fleet(
    db: Session,
    stops: list[OptimizeStopInput],
    selections: list[FleetVehicleSelection],
    require_monetary_cost: bool = False,
    require_hub_routing: bool = False,
    max_route_duration_seconds: float = 12 * 60 * 60,
) -> OptimizeFleetResponse:
    """Assigns trips across a fleet and sequences each vehicle's stops, using REAL
    hub coordinates and cost rates resolved from the database.

    Layering mirrors the single-vehicle path: this module owns real-world I/O (one
    OSRM matrix call covering stops + hubs, one config read) and the trip->job
    translation; every combinatorial decision and hard-constraint check happens in
    ml/src/optimizer/fleet.py, which reuses opt.route_is_feasible unchanged for
    precedence and capacity.

    Business outcomes come back as a typed `status` with HTTP 200. Nothing here
    substitutes a default for missing configuration - an absent rate is reported,
    never costed at zero.
    """
    if len(stops) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 stops to optimize")
    if not selections:
        raise HTTPException(status_code=400, detail="Need at least 1 vehicle to optimize a fleet")
    if max_route_duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="Maximum route duration must be greater than zero")

    # Imported drivers can predate their app-owned cost rows. Complete only
    # missing rows before monetary validation; configured rates stay unchanged.
    ensure_driver_cost_configuration(db)

    jobs = _build_jobs(stops)
    availability_refusal = _availability_refusal(db, selections, jobs)
    if availability_refusal:
        return availability_refusal
    # Fleet dispatches are always depot-to-depot.  Keeping this mandatory at
    # the service boundary prevents a non-UI caller from accidentally getting
    # an open route that omits its hub approach/return legs from the cost.
    configs = [resolve_vehicle_config(db, s.vehicle_id, require_hub=True) for s in selections]

    # 1) Capacity cannot be guaranteed for cargo nobody has weighed.
    unweighed = _unweighed_trip_ids(stops)
    capacity_constrained = any(c.capacity_kg is not None for c in configs)
    if unweighed and capacity_constrained:
        return _refusal(
            "MISSING_REQUIRED_DATA",
            jobs,
            [
                f"Weight is required for {t} before a capacity-constrained dispatch can be created."
                for t in unweighed
            ],
        )

    # 2) Every dispatched fleet route starts and ends at its configured hub.
    # `end_hub` defaults to `start_hub` in config resolution, so both are
    # required here even for callers that omitted the legacy request flag.
    missing_hubs = [c.vehicle_id for c in configs if c.start_hub is None or c.end_hub is None]
    if missing_hubs:
        return _refusal(
            "MISSING_HUB_DATA",
            jobs,
            [f"No complete hub configuration for vehicle {v}." for v in missing_hubs],
        )

    # 3) Cost rates, when the caller needs the answer denominated in currency.
    # A selected driver's unknown hourly rate is not a zero-rate agreement.
    driver_by_vehicle = {s.vehicle_id: s.driver_id for s in selections}
    driver_rates = {s.vehicle_id: resolve_driver_cost_per_hour(db, s.driver_id) for s in selections}
    rate_gaps = sorted({m for c in configs for m in c.missing})
    missing_driver_rates = [
        f"{vehicle_id}: driver {driver_id} cost_per_hour"
        for vehicle_id, driver_id in driver_by_vehicle.items()
        if driver_id and driver_rates[vehicle_id] is None
    ]
    if require_monetary_cost and (any(not c.is_fully_costed for c in configs) or missing_driver_rates):
        return _refusal(
            "MISSING_COST_DATA", jobs,
            [f"Missing cost configuration: {g}" for g in [*rate_gaps, *missing_driver_rates]],
        )

    points, hub_idx_by_vehicle = build_hub_nodes(stops, configs)
    durations, distances = await _fetch_matrices(points)

    ml_vehicles = []
    for cfg in configs:
        start_idx, end_idx = hub_idx_by_vehicle.get(cfg.vehicle_id, (None, None))
        ml_vehicles.append(
            {
                "vehicle_id": cfg.vehicle_id,
                "capacity_kg": cfg.capacity_kg,
                "avg_kmpl_rated": cfg.avg_kmpl_rated,
                "fuel_price_per_l": cfg.fuel_price_per_l,
                # An unconfigured fixed cost contributes 0 to the sum, but the
                # response's cost_is_monetary flag and `warnings` are what tell the
                # caller the figure isn't a complete cost - it is never presented
                # as if the rate were known to be zero.
                "fixed_cost": cfg.fixed_route_cost or 0.0,
                "driver_id": driver_by_vehicle.get(cfg.vehicle_id),
                "start_idx": start_idx,
                "end_idx": end_idx,
                # Rates travel per-vehicle: a heterogeneous fleet has a different
                # per-km cost per truck and a different hourly cost per driver, so
                # one shared pair would charge the wrong rate to every vehicle but
                # one.
                "cost_per_km": cfg.cost_per_km,
                "driver_cost_per_hour": driver_rates.get(cfg.vehicle_id),
                "max_route_duration_seconds": max_route_duration_seconds,
            }
        )

    try:
        result = await ml_client.optimize_fleet_routes(
            {
                "jobs": jobs,
                "vehicles": ml_vehicles,
                "duration_matrix": durations,
                "distance_matrix": distances,
            }
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Optimization service error: {exc.response.status_code} {exc.response.text}"
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Optimization service unavailable: {exc}")

    validation_failure = _validate_optimizer_result(
        result, jobs, configs, hub_idx_by_vehicle, durations, distances, driver_rates,
        max_route_duration_seconds,
    )
    if validation_failure:
        status, reasons = validation_failure
        return _refusal(status, jobs, reasons)

    return OptimizeFleetResponse(
        # Keep the ML service's internal solver wording private; callers need a
        # business outcome that specifically says no fleet assignment exists.
        status=_result_status(result),
        routes=[
            FleetVehicleRouteOut(
                vehicle_id=r["vehicle_id"],
                driver_id=r.get("driver_id"),
                # Hub nodes sit past the end of `stops`, so they carry no stop key
                # and are filtered out of the client-facing order.
                order=[stops[i].key for i in r["order"] if i < len(stops)],
                trip_ids=r["trip_ids"],
                metrics=FleetRouteMetrics(**r["metrics"]),
            )
            for r in result["routes"]
        ],
        unassigned_trip_ids=result["unassigned_trip_ids"],
        totals=FleetRouteMetrics(**result["totals"]),
        vehicles_used=result["vehicles_used"],
        explanation=result["explanation"],
        warnings=[f"Missing cost configuration: {g}" for g in rate_gaps],
        unassigned_diagnostics=result.get("unassigned_diagnostics", []),
    )


_ACTIVE_ROUTE_STATUSES = {"planned", "scheduled", "in-transit"}
_UNAVAILABLE_VEHICLE_STATUSES = {"maintenance", "retired", "inactive", "unavailable", "out-of-service"}
_UNAVAILABLE_DRIVER_STATUSES = {"off-duty", "inactive", "unavailable", "suspended"}


def _availability_refusal(db: Session, selections: list[FleetVehicleSelection], jobs: list[dict]) -> OptimizeFleetResponse | None:
    """Keep the optimizer from planning a resource that is unavailable now.

    Fleet planning does not yet carry a requested dispatch time/range, so any
    existing planned, scheduled or in-transit route is treated as an overlap.
    This mirrors the roster availability shown in the UI and makes the API safe
    when called without the UI.
    """
    vehicle_ids = [selection.vehicle_id for selection in selections]
    duplicate_vehicles = sorted({vehicle_id for vehicle_id in vehicle_ids if vehicle_ids.count(vehicle_id) > 1})
    vehicles = {vehicle.vehicle_id: vehicle for vehicle in db.query(Vehicle).filter(Vehicle.vehicle_id.in_(vehicle_ids)).all()}
    active_vehicle_ids = {
        vehicle_id for (vehicle_id,) in db.query(Route.vehicle_id)
        .filter(Route.vehicle_id.in_(vehicle_ids), func.lower(Route.status).in_(_ACTIVE_ROUTE_STATUSES)).distinct().all()
    }
    busy_telemetry_ids = {
        vehicle_id for (vehicle_id,) in db.query(RealtimeFleetStatus.vehicle_id)
        .filter(RealtimeFleetStatus.vehicle_id.in_(vehicle_ids), RealtimeFleetStatus.current_trip_id.isnot(None)).all()
    }
    vehicle_issues = [
        f"Vehicle {vehicle_id}: " + (
            "selected more than once" if vehicle_id in duplicate_vehicles
            else "not found" if vehicle_id not in vehicles
            else "already assigned to an active route" if vehicle_id in active_vehicle_ids
            else "currently on a trip" if vehicle_id in busy_telemetry_ids
            else f"status is {vehicles[vehicle_id].status}"
        )
        for vehicle_id in vehicle_ids
        if vehicle_id in duplicate_vehicles
        or vehicle_id not in vehicles
        or vehicle_id in active_vehicle_ids
        or vehicle_id in busy_telemetry_ids
        or (vehicles[vehicle_id].status or "").lower() in _UNAVAILABLE_VEHICLE_STATUSES
    ]
    if vehicle_issues:
        return _refusal("VEHICLE_UNAVAILABLE", jobs, vehicle_issues)

    selections_without_driver = [selection.vehicle_id for selection in selections if not selection.driver_id]
    if selections_without_driver:
        return _refusal(
            "DRIVER_UNAVAILABLE",
            jobs,
            [f"Vehicle {vehicle_id}: a dispatch driver is required." for vehicle_id in selections_without_driver],
        )

    driver_ids = [selection.driver_id for selection in selections if selection.driver_id]
    duplicate_drivers = sorted({driver_id for driver_id in driver_ids if driver_ids.count(driver_id) > 1})
    drivers = {driver.driver_id: driver for driver in db.query(Driver).filter(Driver.driver_id.in_(driver_ids)).all()}
    active_driver_ids = {
        driver_id for (driver_id,) in db.query(Route.driver_id)
        .filter(Route.driver_id.in_(driver_ids), func.lower(Route.status).in_(_ACTIVE_ROUTE_STATUSES)).distinct().all()
    }
    in_transit_driver_ids = {
        driver_id for (driver_id,) in db.query(Trip.driver_id)
        .filter(Trip.driver_id.in_(driver_ids), func.lower(Trip.status) == "in-transit").distinct().all()
    }
    driver_issues = [
        f"Driver {driver_id}: " + (
            "selected more than once" if driver_id in duplicate_drivers
            else "not found" if driver_id not in drivers
            else "already assigned to an active route" if driver_id in active_driver_ids
            else "currently on a trip" if driver_id in in_transit_driver_ids
            else f"status is {drivers[driver_id].status}"
        )
        for driver_id in driver_ids
        if driver_id in duplicate_drivers
        or driver_id not in drivers
        or driver_id in active_driver_ids
        or driver_id in in_transit_driver_ids
        or (drivers[driver_id].status or "").lower() in _UNAVAILABLE_DRIVER_STATUSES
    ]
    return _refusal("DRIVER_UNAVAILABLE", jobs, driver_issues) if driver_issues else None


def _result_status(result: dict) -> str:
    """Derive the business outcome from the validated assignment, not a remote label."""
    unassigned = result.get("unassigned_trip_ids", [])
    if not unassigned:
        return "SUCCESS"
    if any(route.get("order") for route in result.get("routes", [])):
        return "PARTIAL"
    return "NO_FEASIBLE_ASSIGNMENT"


def _validate_optimizer_result(
    result: dict,
    jobs: list[dict],
    configs: list[ResolvedVehicleConfig],
    hub_indices: dict[str, tuple[int | None, int | None]],
    durations: list[list[float]],
    distances: list[list[float]],
    driver_rates: dict[str, float | None],
    max_route_duration_seconds: float,
) -> tuple[str, list[str]] | None:
    """Independently validate the ML response before it reaches users.

    This deliberately replays route legs from the OSRM matrices instead of
    trusting solver totals.  It catches missing hub legs, duplicated/missing
    stops, precedence/capacity breaches and incorrect fuel/driver/distance
    costing at the API boundary.
    """
    expected_ids = {job["trip_id"] for job in jobs}
    seen_ids: list[str] = []
    config_by_vehicle = {config.vehicle_id: config for config in configs}
    capacity_by_vehicle = {config.vehicle_id: config.capacity_kg for config in configs}
    weight_by_stop = {job["pickup_stop_index"]: job["load_weight_kg"] for job in jobs}
    weight_by_stop.update({job["delivery_stop_index"]: -job["load_weight_kg"] for job in jobs})
    pair_stops = {job["trip_id"]: (job["pickup_stop_index"], job["delivery_stop_index"]) for job in jobs}
    trip_by_stop = {
        stop: job["trip_id"]
        for job in jobs
        for stop in (job["pickup_stop_index"], job["delivery_stop_index"])
    }
    allowed_by_trip = {job["trip_id"]: job.get("allowed_vehicle_ids") for job in jobs}
    route_vehicle_ids: set[str] = set()
    expected_totals = _empty_metrics().model_dump()
    active_monetary: list[bool] = []

    for route in result.get("routes", []):
        vehicle_id = route.get("vehicle_id")
        if vehicle_id not in config_by_vehicle or vehicle_id in route_vehicle_ids:
            return "NO_FEASIBLE_SOLUTION", ["Optimizer response contains an unknown or duplicate vehicle route"]
        route_vehicle_ids.add(vehicle_id)
        order = route.get("order", [])
        trip_ids = route.get("trip_ids", [])
        seen_ids.extend(trip_ids)
        start_idx, end_idx = hub_indices.get(vehicle_id, (None, None))
        if route.get("full_sequence") != [start_idx, *order, end_idx]:
            return "PICKUP_DROP_VIOLATION", [f"{vehicle_id}: route does not begin and end at its configured hub"]
        if len(order) != len(set(order)) or any(stop not in trip_by_stop for stop in order):
            return "PICKUP_DROP_VIOLATION", [f"{vehicle_id}: route contains duplicate or unknown stops"]
        route_trip_ids = {trip_by_stop[stop] for stop in order}
        if route_trip_ids != set(trip_ids):
            return "PICKUP_DROP_VIOLATION", [f"{vehicle_id}: route stops and trip assignments disagree"]
        running_load = 0.0
        for trip_id in trip_ids:
            pickup, delivery = pair_stops.get(trip_id, (None, None))
            if pickup not in order or delivery not in order or order.index(pickup) >= order.index(delivery):
                return "PICKUP_DROP_VIOLATION", [f"{vehicle_id}: pickup must precede delivery for {trip_id}"]
            allowed = allowed_by_trip[trip_id]
            if allowed and vehicle_id not in allowed:
                return "NO_FEASIBLE_SOLUTION", [f"{vehicle_id}: incompatible with trip {trip_id}"]
        for stop in order:
            running_load += weight_by_stop.get(stop, 0.0)
            capacity = capacity_by_vehicle.get(vehicle_id)
            if capacity is not None and running_load > capacity + 1e-6:
                return "CAPACITY_VIOLATION", [f"{vehicle_id}: running load {running_load:g} kg exceeds {capacity:g} kg"]
            if running_load < -1e-6:
                return "PICKUP_DROP_VIOLATION", [f"{vehicle_id}: delivery occurs before its pickup"]
        metric_failure = _validate_route_metrics(
            route, order, trip_ids, config_by_vehicle[vehicle_id], driver_rates.get(vehicle_id),
            start_idx, end_idx, jobs, durations, distances, max_route_duration_seconds,
        )
        if metric_failure:
            status = "ROUTE_DURATION_VIOLATION" if metric_failure.startswith("duration ") else "NO_FEASIBLE_SOLUTION"
            return status, [f"{vehicle_id}: {metric_failure}"]
        if order:
            metrics = route.get("metrics", {})
            for field in expected_totals:
                if field == "peak_load_kg":
                    # Fleet peak is a maximum across independent vehicle routes,
                    # not an additive total.
                    expected_totals[field] = max(expected_totals[field], float(metrics.get(field, 0.0)))
                elif field != "cost_is_monetary":
                    expected_totals[field] += float(metrics.get(field, 0.0))
            active_monetary.append(bool(metrics.get("cost_is_monetary")))
    accounted_ids = set(seen_ids) | set(result.get("unassigned_trip_ids", []))
    unassigned_ids = result.get("unassigned_trip_ids", [])
    if len(seen_ids) != len(set(seen_ids)) or len(unassigned_ids) != len(set(unassigned_ids)) or accounted_ids != expected_ids:
        return "NO_FEASIBLE_SOLUTION", ["Optimizer response duplicated or dropped one or more dispatch jobs"]
    totals = result.get("totals", {})
    expected_totals["cost_is_monetary"] = bool(active_monetary) and all(active_monetary)
    for field, expected in expected_totals.items():
        actual = totals.get(field)
        if field == "cost_is_monetary":
            if actual is not expected:
                return "NO_FEASIBLE_SOLUTION", ["Fleet total monetary flag is inconsistent with route costs"]
        elif actual is None or not isclose(float(actual), expected, rel_tol=1e-7, abs_tol=1e-5):
            return "NO_FEASIBLE_SOLUTION", [f"Fleet total {field} does not reconcile with route totals"]
    return None


def _validate_route_metrics(
    route: dict,
    order: list[int],
    trip_ids: list[str],
    config: ResolvedVehicleConfig,
    driver_rate: float | None,
    start_idx: int | None,
    end_idx: int | None,
    jobs: list[dict],
    durations: list[list[float]],
    distances: list[list[float]],
    max_route_duration_seconds: float,
) -> str | None:
    """Replay the current fleet cost model without relying on solver totals."""
    metrics = route.get("metrics", {})
    if not order:
        if any(float(metrics.get(field, 0.0)) for field in (
            "distance_meters", "duration_seconds", "fuel_liters", "fuel_cost", "driver_cost",
            "operating_cost", "fixed_cost", "peak_load_kg", "total_cost",
        )):
            return "idle route has non-zero metrics"
        return None

    full_sequence = [start_idx, *order, end_idx]
    load_by_stop = {job["pickup_stop_index"]: job["load_weight_kg"] for job in jobs}
    load_by_stop.update({job["delivery_stop_index"]: -job["load_weight_kg"] for job in jobs})
    running_load = 0.0
    loads_after_stop: dict[int, float] = {}
    for stop in order:
        running_load += load_by_stop[stop]
        loads_after_stop[stop] = running_load

    distance_meters = duration_seconds = fuel_liters = 0.0
    can_fuel = bool(config.avg_kmpl_rated and config.avg_kmpl_rated > 0 and config.fuel_price_per_l is not None)
    for index, (origin, destination) in enumerate(zip(full_sequence, full_sequence[1:])):
        if origin is None or destination is None:
            return "missing hub index"
        leg_distance = float(distances[origin][destination])
        distance_meters += leg_distance
        load = 0.0 if index == 0 else loads_after_stop.get(origin, 0.0)
        utilization = (
            max(0.0, min(load / float(config.capacity_kg), 1.0))
            if config.capacity_kg and config.capacity_kg > 0
            else 0.0
        )
        duration_seconds += float(durations[origin][destination]) / max(1.0 - 0.15 * utilization, 0.30)
        if can_fuel:
            kmpl = float(config.avg_kmpl_rated) / (1.0 + 0.25 * utilization)
            fuel_liters += (leg_distance / 1000.0) / kmpl

    if duration_seconds > max_route_duration_seconds + 1e-6:
        return f"duration {duration_seconds:g}s exceeds the {max_route_duration_seconds:g}s maximum"

    fuel_cost = fuel_liters * float(config.fuel_price_per_l) if can_fuel else 0.0
    driver_cost = duration_seconds / 3600.0 * driver_rate if driver_rate is not None else 0.0
    operating_cost = distance_meters / 1000.0 * config.cost_per_km if config.cost_per_km is not None else 0.0
    fixed_cost = config.fixed_route_cost or 0.0
    monetary = can_fuel or driver_rate is not None or config.cost_per_km is not None
    total_cost = fuel_cost + driver_cost + operating_cost + fixed_cost if monetary else duration_seconds + fixed_cost
    expected = {
        "distance_meters": distance_meters,
        "duration_seconds": duration_seconds,
        "fuel_liters": fuel_liters,
        "fuel_cost": fuel_cost,
        "driver_cost": driver_cost,
        "operating_cost": operating_cost,
        "fixed_cost": fixed_cost,
        "peak_load_kg": max(loads_after_stop.values(), default=0.0),
        "total_cost": total_cost,
    }
    for field, value in expected.items():
        actual = metrics.get(field)
        if actual is None or not isclose(float(actual), value, rel_tol=1e-7, abs_tol=1e-5):
            return f"reported {field} does not match the route legs"
    if metrics.get("cost_is_monetary") is not monetary:
        return "reported monetary flag does not match available cost data"
    return None
