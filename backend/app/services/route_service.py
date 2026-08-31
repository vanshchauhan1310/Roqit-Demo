import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Set

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.driver import Driver
from app.models.trip import RESOLVED_STATUSES, Trip
from app.models.vehicle import Vehicle
from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.schemas.route import FleetPlanCreateRequest, RouteCreate, RouteStopCreate, RouteAssignRequest, TripLoadInput
from app.services.eta_service import WEATHER_ETA_MULTIPLIERS
from app.services.geocode_client import geocode_address
from app.services.osrm_client import get_route_duration_hours
from app.services.weather_client import fetch_weather, map_condition_to_ml_vocabulary

# Cached per-stop weather is refetched once it's older than this.
WEATHER_STALE_AFTER = timedelta(hours=1)


class InsufficientTripsError(ValueError):
    pass


class TripNotFoundError(ValueError):
    pass


class PrecedenceViolationError(ValueError):
    def __init__(self, trip_id: str):
        self.trip_id = trip_id
        super().__init__(f"Precedence violation: delivery before pickup for trip {trip_id}")


class StopSetMismatchError(ValueError):
    pass


class LoadExceedsVehicleCapacityError(ValueError):
    pass


class DriverUnavailableError(ValueError):
    pass


class VehicleUnavailableError(ValueError):
    pass


# Statuses the lazy auto-transition is allowed to touch — never overrides a
# manually-set Completed/Cancelled status.
_AUTO_ROUTE_STATUSES = {"planned", "scheduled", "in-transit"}


def _apply_auto_status_transition(route: Route, now: datetime) -> bool:
    """Advances the route to In-Transit once its pickup_time has passed.

    Called lazily whenever a route is read (list/get), mirroring the trip
    auto-status-transition pattern — there is no background scheduler.
    """
    if not route.status or route.status.lower() not in _AUTO_ROUTE_STATUSES:
        return False
    if route.pickup_time and now >= route.pickup_time:
        if route.status != "in-transit":
            route.status = "in-transit"
            return True
    return False


def _apply_auto_stop_transitions(route: Route, now: datetime) -> bool:
    """Marks any stop whose ETA has passed as done (pending -> done).

    Same lazy pattern as the route status transition — runs on every read and
    only commits when something actually changed.
    """
    changed = False
    for stop in route.stops:
        if stop.status != "pending":
            continue
        if stop.eta and now >= stop.eta:
            stop.status = "done"
            changed = True
    return changed


def _apply_auto_completion(db: Session, route: Route, now: datetime) -> bool:
    """Once every stop on a route is done, completes the route and frees its
    driver and vehicle so they can be assigned to the next route.

    Same lazy pattern as the other transitions — runs on every read, only
    commits when something changed. Driver freedness is derived from trips
    (roster marks a driver on-trip while any of their trips is In-Transit), so
    the route's trips are flipped to Delivered; the vehicle's
    realtime_fleet_status.current_trip_id is cleared, which is exactly what
    the vehicle roster's on-trip flag reads.
    """
    if not route.stops or route.status.lower() not in _AUTO_ROUTE_STATUSES:
        return False
    if not all(stop.status == "done" for stop in route.stops):
        return False

    changed = False
    for stop in route.stops:
        if not stop.trip_id:
            continue
        trip = db.get(Trip, stop.trip_id)
        if trip is not None and trip.status not in RESOLVED_STATUSES:
            trip.status = "Delivered"
            trip.actual_delivery_time = now
            db.add(trip)
            changed = True

    if route.vehicle_id:
        realtime = (
            db.query(RealtimeFleetStatus).filter(RealtimeFleetStatus.vehicle_id == route.vehicle_id).first()
        )
        if realtime is not None and realtime.current_trip_id:
            realtime.current_trip_id = None
            db.add(realtime)
            changed = True

    if route.status != "delivered":
        route.status = "delivered"
        db.add(route)
        changed = True

    return changed


def create_route(db: Session, route_in: RouteCreate) -> Route:
    route = Route(trip_id=route_in.trip_id, name=route_in.name)
    db.add(route)
    db.flush()

    for position, stop_in in enumerate(route_in.stops, start=1):
        stop_data = stop_in.model_dump()
        if stop_data.get("sequence") is None:
            stop_data["sequence"] = position
        db.add(RouteStop(route_id=route.route_id, **stop_data))

    db.commit()
    db.refresh(route)
    return route


def create_fleet_plan_routes(db: Session, plan: FleetPlanCreateRequest) -> list[Route]:
    """Persist reviewed, unsplit optimizer routes atomically."""
    if not plan.routes:
        raise ValueError("A fleet plan needs at least one non-empty route")

    all_trip_ids = [stop.trip_id for route in plan.routes for stop in route.stops]
    trips = db.query(Trip).filter(Trip.trip_id.in_(set(all_trip_ids))).all()
    trips_by_id = {trip.trip_id: trip for trip in trips}
    missing = sorted(set(all_trip_ids) - set(trips_by_id))
    if missing:
        raise TripNotFoundError(f"Trip(s) not found: {', '.join(missing)}")

    seen_trip_ids: set[str] = set()
    persisted: list[Route] = []
    try:
        for route_in in plan.routes:
            if not route_in.stops:
                raise ValueError(f"Vehicle {route_in.vehicle_id} has no stops")
            if not route_in.driver_id:
                raise DriverUnavailableError(
                    f"DRIVER_UNAVAILABLE: vehicle {route_in.vehicle_id} needs an assigned driver"
                )
            by_trip: dict[str, list[str]] = {}
            for stop in route_in.stops:
                by_trip.setdefault(stop.trip_id, []).append(stop.stop_type)
            for trip_id, types in by_trip.items():
                if trip_id in seen_trip_ids:
                    raise ValueError(f"Trip {trip_id} appears in more than one vehicle route")
                if types.count("pickup") != 1 or types.count("delivery") != 1 or len(types) != 2:
                    raise ValueError(f"Trip {trip_id} must have exactly one pickup and one delivery")
                if types.index("pickup") > types.index("delivery"):
                    raise PrecedenceViolationError(trip_id)
                seen_trip_ids.add(trip_id)

            vehicle = db.get(Vehicle, route_in.vehicle_id)
            if vehicle is None:
                raise ValueError(f"Vehicle {route_in.vehicle_id} not found")
            if (vehicle.status or "").lower() in {"maintenance", "retired", "inactive", "unavailable", "out-of-service"}:
                raise VehicleUnavailableError(f"VEHICLE_UNAVAILABLE: vehicle {route_in.vehicle_id} is unavailable")
            if db.query(Route.route_id).filter(
                Route.vehicle_id == route_in.vehicle_id,
                func.lower(Route.status).in_(_AUTO_ROUTE_STATUSES),
            ).first():
                raise VehicleUnavailableError(
                    f"VEHICLE_UNAVAILABLE: vehicle {route_in.vehicle_id} already has an active route"
                )
            driver = db.get(Driver, route_in.driver_id)
            if driver is None or (driver.status or "").lower() in {"off-duty", "inactive", "unavailable", "suspended"}:
                raise DriverUnavailableError(f"DRIVER_UNAVAILABLE: driver {route_in.driver_id} is unavailable")
            if db.query(Route.route_id).filter(
                Route.driver_id == route_in.driver_id,
                func.lower(Route.status).in_(_AUTO_ROUTE_STATUSES),
            ).first():
                raise DriverUnavailableError(
                    f"DRIVER_UNAVAILABLE: driver {route_in.driver_id} already has an active route"
                )
            if vehicle.load_capacity_kg is not None:
                running_load_kg = 0.0
                peak_load_kg = 0.0
                for stop_in in route_in.stops:
                    weight_kg = trips_by_id[stop_in.trip_id].load_weight_kg or 0.0
                    running_load_kg += weight_kg if stop_in.stop_type == "pickup" else -weight_kg
                    peak_load_kg = max(peak_load_kg, running_load_kg)
                if peak_load_kg > vehicle.load_capacity_kg:
                    raise LoadExceedsVehicleCapacityError(
                        f"This stop order carries {peak_load_kg} kg at once, exceeding vehicle "
                        f"{route_in.vehicle_id}'s capacity of {vehicle.load_capacity_kg} kg"
                    )
            route = Route(
                trip_id=next(iter(by_trip)) if len(by_trip) == 1 else None,
                name=route_in.name or f"Fleet route - {route_in.vehicle_id}",
                driver_id=route_in.driver_id,
                vehicle_id=route_in.vehicle_id,
                pickup_time=plan.pickup_time,
            )
            db.add(route)
            db.flush()
            for sequence, stop_in in enumerate(route_in.stops, start=1):
                trip = trips_by_id[stop_in.trip_id]
                pickup = stop_in.stop_type == "pickup"
                db.add(RouteStop(
                    route_id=route.route_id, trip_id=trip.trip_id, sequence=sequence,
                    stop_type=stop_in.stop_type, address=trip.origin if pickup else trip.destination,
                    latitude=trip.gps_start_lat if pickup else trip.gps_end_lat,
                    longitude=trip.gps_start_lon if pickup else trip.gps_end_lon,
                ))
            for trip_id in by_trip:
                trip = trips_by_id[trip_id]
                trip.driver_id = route_in.driver_id
                trip.vehicle_id = route_in.vehicle_id
                trip.pickup_time = plan.pickup_time
                if vehicle.vehicle_type:
                    trip.vehicle_type = vehicle.vehicle_type
                db.add(trip)
            persisted.append(route)
        db.commit()
        for route in persisted:
            db.refresh(route)
        return persisted
    except Exception:
        db.rollback()
        raise


def get_route(db: Session, route_id: uuid.UUID) -> Route | None:
    route = db.get(Route, route_id)
    if not route:
        return None

    now = datetime.now(timezone.utc)
    changed_status = _apply_auto_status_transition(route, now)
    changed_stops = _apply_auto_stop_transitions(route, now)
    changed_completion = _apply_auto_completion(db, route, now)
    if changed_status or changed_stops or changed_completion:
        db.add(route)
        db.commit()
        db.refresh(route)
    return route


def list_routes(db: Session, skip: int = 0, limit: int = 100, trip_id: str | None = None) -> list[Route]:
    query = db.query(Route)
    if trip_id:
        # Legacy single-trip links (Route.trip_id) plus the new grouped model
        # where a trip belongs to a route via its RouteStop rows.
        stop_route_ids = select(RouteStop.route_id).where(RouteStop.trip_id == trip_id).scalar_subquery()
        query = query.filter(or_(Route.trip_id == trip_id, Route.route_id.in_(stop_route_ids)))
    routes = query.order_by(Route.created_at.desc()).offset(skip).limit(limit).all()

    # Lazy auto-transitions: pickup_time passed -> In-Transit; stop ETA passed -> done;
    # all stops done -> Delivered and driver/vehicle freed.
    now = datetime.now(timezone.utc)
    any_changed = False
    for route in routes:
        changed_status = _apply_auto_status_transition(route, now)
        changed_stops = _apply_auto_stop_transitions(route, now)
        changed_completion = _apply_auto_completion(db, route, now)
        if changed_status or changed_stops or changed_completion:
            db.add(route)
            any_changed = True

    if any_changed:
        db.commit()
    return routes


def update_route_status(db: Session, route: Route, status: str) -> Route:
    route.status = status
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def assign_trip(db: Session, route: Route, trip_id: str) -> Route:
    route.trip_id = trip_id
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


async def ensure_stop_coordinates(db: Session, route: Route) -> bool:
    """Lazily backfills lat/lon for any stop that has an address but no coordinates yet
    (e.g. routes seeded from historical trips, or added without using the Locate button).

    Self-healing on first read, same pattern as the trip auto-status-transition —
    once a stop is geocoded and committed, it's never re-geocoded.
    """
    changed = False
    for stop in route.stops:
        if stop.latitude is not None or stop.longitude is not None or not stop.address:
            continue
        try:
            result = await geocode_address(stop.address)
        except Exception:
            continue
        stop.latitude = result.lat
        stop.longitude = result.lng
        db.add(stop)
        changed = True
        await asyncio.sleep(1)  # respect Nominatim's ~1 request/second usage policy

    if changed:
        db.commit()
        db.refresh(route)
    return changed


async def _refresh_stop_weather(stop: RouteStop, now: datetime) -> bool:
    try:
        result = await fetch_weather(stop.latitude, stop.longitude)
    except Exception:
        return False
    stop.weather_condition = result.condition
    stop.weather_updated_at = now
    return True


async def ensure_stop_weather(db: Session, route: Route) -> bool:
    """Lazily (re)fetches per-stop weather for any geocoded stop whose cached weather
    is missing or older than WEATHER_STALE_AFTER. Persisted on route_stops so repeat
    reads within the hour don't re-hit OpenWeather. Unlike Nominatim, OpenWeather has
    no 1 req/sec restriction, so stale stops are refreshed concurrently.
    """
    now = datetime.now(timezone.utc)
    stale_stops = [
        stop
        for stop in route.stops
        if stop.latitude is not None
        and stop.longitude is not None
        and (stop.weather_updated_at is None or now - stop.weather_updated_at >= WEATHER_STALE_AFTER)
    ]
    if not stale_stops:
        return False

    results = []
    for stop in stale_stops:
        results.append(await _refresh_stop_weather(stop, now))
    changed = any(results)
    for stop in stale_stops:
        db.add(stop)

    if changed:
        db.commit()
        db.refresh(route)
    return changed


async def compute_weather_eta(db: Session, route: Route) -> datetime | None:
    """Rule-based, NOT ML: walks the route's geocoded stops in sequence, computing
    each leg's real OSRM duration adjusted by that leg's destination-stop weather
    (via eta_service's hand-coded multiplier table), starting from the route's
    pickup_time. Persists each stop's `eta` column so it doesn't get recomputed
    on every read. Returns the final stop's ETA (the route-level "weather_eta"),
    or None if there's no pickup_time or no geocoded stops.
    """
    start_time = route.pickup_time
    if start_time is None and route.trip_id:
        trip = db.get(Trip, route.trip_id)
        start_time = trip.pickup_time if trip else None
    if start_time is None:
        return None

    stops = sorted(route.stops, key=lambda s: s.sequence)
    geocoded = [s for s in stops if s.latitude is not None and s.longitude is not None]
    if not geocoded:
        return None

    current_time = start_time
    changed = False

    # First stop is reached at pickup time itself.
    if geocoded[0].eta != current_time:
        geocoded[0].eta = current_time
        db.add(geocoded[0])
        changed = True

    for prev, stop in zip(geocoded, geocoded[1:]):
        base_hours = await get_route_duration_hours(prev.latitude, prev.longitude, stop.latitude, stop.longitude)
        if base_hours is None:
            base_hours = 0.0

        ml_condition = map_condition_to_ml_vocabulary(stop.weather_condition) if stop.weather_condition else None
        multiplier = WEATHER_ETA_MULTIPLIERS.get(ml_condition, 1.0) if ml_condition else 1.0

        current_time = current_time + timedelta(hours=base_hours * multiplier)
        if stop.eta != current_time:
            stop.eta = current_time
            db.add(stop)
            changed = True

    if changed:
        db.commit()
        db.refresh(route)

    return geocoded[-1].eta


def propagate_planned_delivery_time(db: Session, route: Route, route_eta: datetime | None) -> None:
    """Mirrors the single route-level pickup_time onto each trip's
    planned_delivery_time as pickup_time + the route's full computed duration
    (the last stop's ETA), and backfills any ML-required fields the trip can
    inherit from its route (vehicle_type from the assigned vehicle, and a
    weather condition from the trip's own pickup-stop weather when the trip
    was created before live weather was available). This is what lets the
    delay/expected-delay ML models run for trips grouped into this route."""
    vehicle = db.get(Vehicle, route.vehicle_id) if route.vehicle_id else None
    weather_by_trip: dict[str, str | None] = {}
    changed = False
    for stop in route.stops:
        if not stop.trip_id:
            continue
        if stop.trip_id not in weather_by_trip:
            weather_by_trip[stop.trip_id] = stop.weather_condition
        trip = db.get(Trip, stop.trip_id)
        if trip is None:
            continue
        trip_changed = False
        if route_eta is not None and trip.planned_delivery_time != route_eta:
            trip.planned_delivery_time = route_eta
            trip_changed = True
        if vehicle is not None and vehicle.vehicle_type and trip.vehicle_type != vehicle.vehicle_type:
            trip.vehicle_type = vehicle.vehicle_type
            trip_changed = True
        stop_weather = weather_by_trip[stop.trip_id]
        if trip.weather_condition is None and stop_weather:
            trip.weather_condition = stop_weather
            trip_changed = True
        if trip_changed:
            db.add(trip)
            changed = True
    if changed:
        db.commit()


def add_stop_to_route(db: Session, route: Route, stop_in: RouteStopCreate) -> RouteStop:
    stop_data = stop_in.model_dump()

    if stop_data.get("sequence") is None:
        max_sequence = db.query(func.max(RouteStop.sequence)).filter(RouteStop.route_id == route.route_id).scalar()
        stop_data["sequence"] = (max_sequence or 0) + 1

    stop = RouteStop(route_id=route.route_id, **stop_data)
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return stop


def _max_cumulative_load_kg(stops: List[RouteStop], loads_by_trip: Dict[str, float]) -> float:
    """Walks `stops` in sequence order and returns the highest load the vehicle ever carries at
    once - +weight at each trip's pickup, -weight at its delivery - not the flat sum of every
    trip's weight. A sequential pickup->drop->pickup->drop route never carries more than the
    single heaviest trip in flight at once, even if the trips' weights summed exceed capacity;
    the flat-sum check this replaces couldn't tell the two cases apart. Mirrors
    ml/src/optimizer/opt.py::_load_at_positions (see WEIGHT_AWARE_ROUTING.md §8)."""
    ordered = sorted(stops, key=lambda s: s.sequence)
    running = 0.0
    peak = 0.0
    for stop in ordered:
        if not stop.trip_id or stop.stop_type not in ("pickup", "delivery"):
            continue
        weight = loads_by_trip.get(stop.trip_id, 0.0) or 0.0
        running += weight if stop.stop_type == "pickup" else -weight
        peak = max(peak, running)
    return peak


def _validate_precedence(stops: List[RouteStop], position: Dict[uuid.UUID, int]) -> None:
    """Validate that for each trip, pickup comes before delivery in the stop order."""
    by_trip: Dict[str, Dict[str, RouteStop]] = {}
    for stop in stops:
        if not stop.trip_id or stop.stop_type not in ("pickup", "delivery"):
            continue  # legacy freestanding waypoints have no pair to check
        by_trip.setdefault(stop.trip_id, {})[stop.stop_type] = stop

    for trip_id, pair in by_trip.items():
        pickup = pair.get("pickup")
        delivery = pair.get("delivery")
        if pickup is None or delivery is None:
            continue
        if position[pickup.stop_id] > position[delivery.stop_id]:
            raise PrecedenceViolationError(trip_id)


def assign_route(db: Session, assign_in: RouteAssignRequest) -> Route:
    if len(assign_in.trip_ids) < 1:
        raise InsufficientTripsError("A route needs at least 1 trip")

    trips = db.query(Trip).filter(Trip.trip_id.in_(assign_in.trip_ids)).all()
    trips_by_id = {t.trip_id: t for t in trips}
    missing = [tid for tid in assign_in.trip_ids if tid not in trips_by_id]
    if missing:
        raise TripNotFoundError(f"Trip(s) not found: {', '.join(missing)}")

    # 1) Write per-trip load onto each Trip row.
    loads_by_trip = {load.trip_id: load for load in assign_in.loads}
    for trip_id, load in loads_by_trip.items():
        trip = trips_by_id[trip_id]
        # An empty route-level field means "keep the recorded consignment
        # weight", not "erase it". The trip remains the source of truth
        # unless a dispatcher deliberately supplies a replacement weight.
        if load.load_weight_kg is not None:
            trip.load_weight_kg = load.load_weight_kg
        trip.load_value = load.load_value

    # 2) Capacity is a multi-trip running-load constraint. Validate the
    # default order this function persists (all pickups, then all deliveries),
    # rather than a flat sum detached from the actual stop sequence.
    vehicle = db.get(Vehicle, assign_in.vehicle_id)
    if vehicle and vehicle.load_capacity_kg is not None:
        # Capacity is determined by the cargo concurrently aboard in this
        # route's persisted default order (all pickups, then all deliveries).
        # Reordering applies the same running-load rule below.
        running_load_kg = 0.0
        peak_load_kg = 0.0
        for trip_id in assign_in.trip_ids:
            running_load_kg += trips_by_id[trip_id].load_weight_kg or 0.0
            peak_load_kg = max(peak_load_kg, running_load_kg)
        if peak_load_kg > vehicle.load_capacity_kg:
            db.rollback()
            raise LoadExceedsVehicleCapacityError(
                f"This stop order carries {peak_load_kg} kg at once, exceeding vehicle "
                f"{assign_in.vehicle_id}'s capacity of {vehicle.load_capacity_kg} kg"
            )

    # 3) Create the Route.
    route = Route(
        name=assign_in.name,
        driver_id=assign_in.driver_id,
        vehicle_id=assign_in.vehicle_id,
        pickup_time=assign_in.pickup_time,
    )
    db.add(route)
    db.flush()  # assigns route.route_id before stops need it as a FK

    # 4) Every trip's pickup stop first, in trip_ids order...
    sequence = 1
    for trip_id in assign_in.trip_ids:
        trip = trips_by_id[trip_id]
        db.add(RouteStop(
            route_id=route.route_id,
            trip_id=trip_id,
            sequence=sequence,
            stop_type="pickup",
            address=trip.origin,
            latitude=trip.gps_start_lat,
            longitude=trip.gps_start_lon,
        ))
        sequence += 1

    # ...then every trip's delivery stop, same order.
    for trip_id in assign_in.trip_ids:
        trip = trips_by_id[trip_id]
        db.add(RouteStop(
            route_id=route.route_id,
            trip_id=trip_id,
            sequence=sequence,
            stop_type="delivery",
            address=trip.destination,
            latitude=trip.gps_end_lat,
            longitude=trip.gps_end_lon,
        ))
        sequence += 1

    # 5) Denormalize driver/vehicle/pickup_time back onto every grouped Trip.
    for trip in trips:
        trip.driver_id = assign_in.driver_id
        trip.vehicle_id = assign_in.vehicle_id
        trip.pickup_time = assign_in.pickup_time
        if vehicle is not None and vehicle.vehicle_type:
            trip.vehicle_type = vehicle.vehicle_type
        db.add(trip)

    db.commit()
    db.refresh(route)
    return route


def reorder_stops(db: Session, route: Route, stop_ids: List[uuid.UUID]) -> Route:
    existing_ids = {stop.stop_id for stop in route.stops}
    if set(stop_ids) != existing_ids or len(stop_ids) != len(existing_ids):
        raise StopSetMismatchError("stop_ids must match the route's current stops exactly")

    position = {stop_id: index for index, stop_id in enumerate(stop_ids)}
    _validate_precedence(route.stops, position)  # raises before anything is touched

    for stop in route.stops:
        stop.sequence = position[stop.stop_id] + 1

    # Check the NEW order's actual concurrent load (not a flat sum) against vehicle capacity -
    # see _max_cumulative_load_kg / WEIGHT_AWARE_ROUTING.md §8. This is the authoritative capacity
    # gate for the route's real, final stop arrangement: assign_route only rejects a trip that
    # couldn't fit in ANY order; whether THIS specific order fits is decided here.
    if route.vehicle_id:
        vehicle = db.get(Vehicle, route.vehicle_id)
        if vehicle and vehicle.load_capacity_kg is not None:
            trip_ids = {stop.trip_id for stop in route.stops if stop.trip_id}
            trips = db.query(Trip).filter(Trip.trip_id.in_(trip_ids)).all()
            loads_by_trip = {t.trip_id: t.load_weight_kg or 0.0 for t in trips}
            peak_kg = _max_cumulative_load_kg(route.stops, loads_by_trip)
            if peak_kg > vehicle.load_capacity_kg:
                db.rollback()
                raise LoadExceedsVehicleCapacityError(
                    f"This stop order carries {peak_kg} kg at once, exceeding vehicle {route.vehicle_id}'s capacity of {vehicle.load_capacity_kg} kg"
                )

    for stop in route.stops:
        db.add(stop)
    db.commit()
    return route
