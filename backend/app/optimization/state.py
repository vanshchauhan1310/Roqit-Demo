"""Assignment-state validation and authoritative load helpers.

This module is the *single* lightweight source of truth for whether a trip's
routing assignment is internally consistent. It intentionally does NOT
participate in route generation, insertion, scoring, or ranking - it only
guards the existing optimization pipeline against operating on invalid state
or violating hard HOS / vehicle-capacity constraints.

The routes/optimizer algorithms themselves are untouched; this layer just
reports and repairs broken assignment state before the existing algorithm
executes, and provides authoritative load figures (derived from
RouteStop/Trip rows rather than cached capacity columns) for constraint
checks.

Note on identifiers: ``Trip.route_id`` is a denormalized **String** while
``Route.route_id`` is a **UUID**. Every comparison here normalises to the
string form to avoid false "no route" lookups.
"""

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.models.vehicle import Vehicle


# Logistics industry standard daily hours-of-service limit. Centralised here
# so the feasibility engine (existing-route insertion) and the assignment
# worker (new-route creation) share one value instead of duplicating it.
MAX_DRIVER_HOS_HOURS = 14.0

# Trip status written by the completion worker once a trip's delivery is done
# (10 minutes after assignment in the demo lifecycle). Completed trips no
# longer occupy vehicle/route capacity - their cargo has been delivered.
COMPLETED_TRIP_STATUS = "completed"

# A driver's 14-hour clock is a *rolling duty window*, not a lifetime total:
# hours assigned to routes created more than DUTY_WINDOW_HOURS ago no longer
# count against the current duty period (the driver has rested / the duty day
# rolled over). Measuring hours as a lifetime accumulation permanently
# saturates every driver once enough routes pile up - nothing can ever be
# assigned again and the Live Ops "queue depth" never drains back to 0.
DUTY_WINDOW_HOURS = MAX_DRIVER_HOS_HOURS


def duty_window_start() -> datetime:
    """UTC instant before which assigned hours fall out of the duty window."""
    return datetime.now(timezone.utc) - timedelta(hours=DUTY_WINDOW_HOURS)

# Route statuses whose cargo/load and driver-time counts as "active".
ACTIVE_STATUSES = ("planned", "active", "in-transit")
# Route statuses whose cargo/load and driver-time counts as "active".
ACTIVE_STATUSES = ("planned", "active", "in-transit")

# ---------------------------------------------------------------------------
# Writer funnel lock (Postgres advisory lock)
#
# Every transaction that MUTATES routes / trips / route_stops (LNS optimizer,
# trip-assignment worker, trip-completion worker) must call
# ``acquire_writer_lock`` FIRST, before touching any rows.
#
# Why: these writers update the same rows (route capacity, trip.route_id,
# RouteStops) but in different orders, so Postgres lock waits occasionally
# form a cycle -> "deadlock detected", which used to abort the whole LNS run.
# With a single transaction-scoped funnel lock taken before any row lock, two
# writers can never hold row locks at the same time, so a writer-vs-writer
# deadlock is structurally impossible. The lock is xact-scoped: it is released
# automatically on commit/rollback, and each LNS iteration's commit creates a
# window in which the short workers can proceed.
# ---------------------------------------------------------------------------
WRITER_XACT_LOCK_KEY = 841302117  # arbitrary fixed constant shared app-wide


def acquire_writer_lock(db: Session, lock_timeout_s: int = 30) -> bool:
    """Block until this transaction holds the writer funnel lock.
    Must be called at the start of any transaction that mutates routes,
    trips, or route_stops. Released automatically at commit/rollback.

    Implementation note: this uses the NON-BLOCKING ``pg_try_advisory_xact_lock``
    in a bounded polling loop instead of a blocking ``pg_advisory_xact_lock``
    with ``SET LOCAL lock_timeout``. The blocking form was observed to ignore
    the server-side lock_timeout (waiters stuck 50s+ on the advisory lock),
    and the waiting session sat "idle in transaction" for the entire wait,
    hoarding its snapshot + the pool connection. The polling form:

    - never blocks inside Postgres (no reliance on lock_timeout semantics)
    - rolls back between polls, so the session is never idle-in-transaction
      for more than ~0.5s (the 90s per-connection circuit breaker stays a
      pure safety net rather than a routine participant)
    - honours the requested bound in Python via a monotonic deadline

    On success the caller keeps mutating in the SAME transaction — the
    xact-scoped advisory lock is then held until the caller's commit/rollback.
    Returns True if the lock was acquired, False if the bound elapsed.
    """
    import time

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    deadline = time.monotonic() + max(1, int(lock_timeout_s))
    while True:
        try:
            got = db.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": WRITER_XACT_LOCK_KEY},
            ).scalar()
        except DBAPIError:
            # Connection-level failure; let the caller's error path handle it.
            return False
        if got:
            return True
        # Busy: release our transaction (and any snapshot it pinned) while we
        # wait so this session can never wedge others into idle-in-transaction
        # related contention.
        try:
            db.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)

# Shared route-duration model (NOT a new algorithm - this is the assignment
# worker's existing estimator, relocated here so the feasibility engine's HOS
# check, the worker's new-route HOS check, and the consistency audit all use
# the SAME numbers. Previously the engine measured travel time only while the
# worker added per-stop service time, so insertions slipped past the limit).
AVG_ROUTE_SPEED_KPH = 40.0
SERVICE_HOURS_PER_STOP = 0.1  # 6 minutes per pickup/delivery stop


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    from math import radians, sin, cos, sqrt, atan2

    R = 6371.0
    lat1, lon1, lat2, lon2 = radians(lat1), radians(lon1), radians(lat2), radians(lon2)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def estimate_route_hours(stops) -> float:
    """Estimated service hours for a stop sequence (travel + per-stop time)."""
    geocoded = [s for s in stops if s.latitude and s.longitude]
    total_km = 0.0
    for prev, stop in zip(geocoded, geocoded[1:]):
        total_km += _haversine_km(prev.latitude, prev.longitude, stop.latitude, stop.longitude)
    return (total_km / AVG_ROUTE_SPEED_KPH) + len(stops) * SERVICE_HOURS_PER_STOP


def estimate_trip_hours(trip: Trip) -> float:
    """Estimated driving hours for a single trip (start -> end)."""
    if trip.gps_start_lat and trip.gps_start_lon and trip.gps_end_lat and trip.gps_end_lon:
        km = _haversine_km(
            trip.gps_start_lat, trip.gps_start_lon,
            trip.gps_end_lat, trip.gps_end_lon,
        )
        return (km / AVG_ROUTE_SPEED_KPH) + 2 * SERVICE_HOURS_PER_STOP
    return SERVICE_HOURS_PER_STOP * 2



class TripAssignmentStatus(Enum):
    """Canonical assignment-state classification for a trip."""

    VALID = "VALID"
    ORPHANED = "ORPHANED"
    MISSING_ROUTE_STOP = "MISSING_ROUTE_STOP"
    MISMATCHED_ROUTE = "MISMATCHED_ROUTE"
    UNASSIGNED = "UNASSIGNED"


def classify_assignment(route_id, route_exists: bool, stop_route_ids) -> TripAssignmentStatus:
    """Pure classification of an assignment given its observed inputs.

    A trip is validly assigned ONLY when all of the following hold:

    - ``route_id`` is set
    - the referenced route exists
    - at least one RouteStop exists for the trip
    - that RouteStop's ``route_id`` matches ``trip.route_id``

    This function has no DB dependency so it can be unit-tested in isolation.
    """
    if not route_id:
        return TripAssignmentStatus.UNASSIGNED
    if not route_exists:
        return TripAssignmentStatus.ORPHANED
    stop_route_ids = {str(s) for s in stop_route_ids} if stop_route_ids else set()
    if not stop_route_ids:
        return TripAssignmentStatus.MISSING_ROUTE_STOP
    if str(route_id) not in stop_route_ids:
        return TripAssignmentStatus.MISMATCHED_ROUTE
    return TripAssignmentStatus.VALID


def _route_from_string_id(db: Session, route_id: str):
    """Look up a route by its string id, tolerant of the str<->UUID split."""
    try:
        rid_uuid = uuid.UUID(str(route_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return db.query(Route).filter(Route.route_id == rid_uuid).first()


def validate_trip_assignment(db: Session, trip: Trip) -> TripAssignmentStatus:
    """Classify a trip's current assignment state against the canonical rule."""
    if not getattr(trip, "route_id", None):
        return TripAssignmentStatus.UNASSIGNED

    route_id = str(trip.route_id)
    route = _route_from_string_id(db, route_id)
    if route is None:
        return TripAssignmentStatus.ORPHANED

    stop_rows = db.query(RouteStop).filter(RouteStop.trip_id == trip.trip_id).all()
    stop_route_ids = {str(s.route_id) for s in stop_rows if s.route_id is not None}
    return classify_assignment(route_id, True, stop_route_ids)
def repair_trip_assignment(db: Session, trip: Trip) -> bool:
    """Repair an invalid assignment in place so the existing assignment
    pipeline can take over. Returns True if anything changed.

    - ORPHANED / MISSING_ROUTE_STOP  -> clear ``route_id`` (trip is genuinely
      unassigned and must be routed again).
    - MISMATCHED_ROUTE              -> the RouteStop is the ground truth of
      where the trip physically sits; align the denormalized ``route_id`` to
      the stop's actual route rather than clearing it.
    - VALID / UNASSIGNED            -> no-op.
    """
    status = validate_trip_assignment(db, trip)
    if status in (TripAssignmentStatus.VALID, TripAssignmentStatus.UNASSIGNED):
        return False

    if status == TripAssignmentStatus.MISMATCHED_ROUTE:
        stop = db.query(RouteStop).filter(RouteStop.trip_id == trip.trip_id).first()
        if stop is not None and stop.route_id is not None:
            trip.route_id = str(stop.route_id)
            db.add(trip)
            return True

    trip.route_id = None
    trip.assigned_at = None
    db.add(trip)
    return True


def route_load_kg(db: Session, route: Route) -> float:
    """Authoritative load currently on a single route, derived from its
    pickup-stop trips (never from the cached ``used_capacity_kg`` column)."""
    if route is None:
        return 0.0

    # SessionLocal runs with autoflush=False, so stops added earlier in the
    # same uncommitted session (e.g. a multi-insertion greedy/LNS batch)
    # would be invisible to the queries below and under-count the load.
    # Flush pending state so aggregate checks always see the full picture.
    if db.new or db.dirty:
        db.flush()

    pickup_ids = [
        s.trip_id
        for s in db.query(RouteStop).filter(
            RouteStop.route_id == route.route_id,
            RouteStop.stop_type == "pickup",
        ).all()
        if s.trip_id
    ]
    if not pickup_ids:
        return 0.0

    # Completed trips have been delivered - their cargo no longer rides on
    # the vehicle. Excluding them here (instead of defaulting to 0.0 via the
    # missing-dict-entry path below) keeps the released capacity explicit.
    loads = dict(
        db.query(Trip.trip_id, Trip.load_weight_kg)
        .filter(
            Trip.trip_id.in_(pickup_ids),
            Trip.status != COMPLETED_TRIP_STATUS,
        )
        .all()
    )
    return float(sum((loads.get(tid, 0.0) or 0.0) for tid in pickup_ids))
def vehicle_active_load_kg(db: Session, vehicle: Vehicle) -> float:
    """Authoritative aggregate load carried by a vehicle across ALL of its
    active routes at once (the hard capacity constraint.)"""
    if vehicle is None or vehicle.vehicle_id is None:
        return 0.0

    # See route_load_kg: flush so same-session insertions are counted.
    if db.new or db.dirty:
        db.flush()

    route_ids = [
        r
        for (r,)in db.query(Route.route_id).filter(
            Route.vehicle_id == vehicle.vehicle_id,
            Route.status.in_(ACTIVE_STATUSES),
        ).all()
    ]
    if not route_ids:
        return 0.0

    pickup_ids = [
        s.trip_id
        for s in db.query(RouteStop).filter(
            RouteStop.route_id.in_(route_ids),
            RouteStop.stop_type == "pickup",
        ).all()
        if s.trip_id
    ]
    if not pickup_ids:
        return 0.0

    loads = dict(
        db.query(Trip.trip_id, Trip.load_weight_kg)
        .filter(
            Trip.trip_id.in_(pickup_ids),
            Trip.status != COMPLETED_TRIP_STATUS,
        )
        .all()
    )
    return float(sum((loads.get(tid, 0.0) or 0.0) for tid in pickup_ids))


def sync_route_capacity(db: Session, route: Route) -> float:
    """Synchronise a route's cached capacity fields from authoritative load.

    Call after any route mutation (destroy, repair, insertion) so the cached
    ``used_capacity_kg`` / ``remaining_capacity_kg`` never drift out of sync
    with the stops that actually carry cargo. Returns the recomputed load."""
    load = route_load_kg(db, route)

    vehicle = db.get(Vehicle, route.vehicle_id) if route.vehicle_id else None
    cap = None
    if vehicle is not None and vehicle.load_capacity_kg is not None:
        cap = vehicle.load_capacity_kg
    elif route.capacity_kg is not None:
        cap = route.capacity_kg

    route.used_capacity_kg = load
    route.remaining_capacity_kg = (cap or 0.0) - load
    db.add(route)
    return load


def delete_routes_safely(db: Session, route_ids) -> None:
    """Transaction-safe route deletion.



    Prevents ``Trip.route_id -> deleted Route`` staleness: every trip that
    references any of the deleted routes (via RouteStop or via the
    denormalized ``route_id``) has its assignment cleared so it can return to
    the existing assignment pipeline. RouteStops and the routes themselves
    are removed per the existing lifecycle. The caller commits."""
    route_ids = [r for r in route_ids if r is not None]
    if not route_ids:
        return

    # Trips physically referenced by the routes' stops.

    stop_trip_ids = {
        s.trip_id
        for s in db.query(RouteStop).filter(RouteStop.route_id.in_(route_ids)).all()
        if s.trip_id
    }


    # Trips whose denormalized route_id points at these routes (string form).
    route_id_strs = {str(r) for r in route_ids}
    dangling = db.query(Trip).filter(Trip.route_id.in_(route_id_strs)).all()


    for trip_id in stop_trip_ids | {t.trip_id for t in dangling}:
        trip = db.get(Trip, trip_id)
        if trip is not None and trip.route_id:
            trip.route_id = None
            db.add(trip)

    db.query(RouteStop).filter(RouteStop.route_id.in_(route_ids)).delete(
        synchronize_session=False
    )
    db.query(Route).filter(Route.route_id.in_(route_ids)).delete(
        synchronize_session=False
    )