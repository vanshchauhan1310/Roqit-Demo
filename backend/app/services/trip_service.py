import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.schemas.trip import TripCreate, TripFilterOptions, TripOutcomeUpdate

# Demo-only: there's no live telemetry feed wired in yet, so every trip gets a deterministic
# "actual" outcome derived from its planned values instead of leaving them NULL forever.
# >1.0 so the demo always shows some real-world overage (detours, traffic) vs the plan.
DEMO_ACTUAL_DISTANCE_FACTOR = 1.12
DEMO_ACTUAL_DELIVERY_OFFSET_MINUTES = 45

# Statuses this lazy transition is allowed to touch — never overrides a manually-set
# Delayed/Cancelled/Delivered status.
_AUTO_TRANSITION_STATUSES = {"scheduled", "in-transit"}


class DuplicateIdError(ValueError):
    pass


def _apply_auto_status_transition(trip: Trip, now: datetime) -> bool:
    """Advances Scheduled -> In-Transit -> Delivered based on pickup_time/actual_delivery_time vs now.

    Called lazily whenever a trip is read (list/get), since there's no background
    scheduler in this demo to do it proactively.
    """
    if not trip.status or trip.status.lower() not in _AUTO_TRANSITION_STATUSES:
        return False

    if trip.actual_delivery_time and now >= trip.actual_delivery_time:
        if trip.status != "Delivered":
            trip.status = "Delivered"
            return True
    elif trip.pickup_time and now >= trip.pickup_time:
        if trip.status != "In-Transit":
            trip.status = "In-Transit"
            return True

    return False


def _generate_trip_id() -> str:
    return f"TRP-{uuid.uuid4().hex[:8].upper()}"


def create_trip(db: Session, trip_in: TripCreate) -> Trip:
    trip_data = trip_in.model_dump()

    if trip_data.get("planned_distance_km") is not None:
        trip_data["actual_distance_km"] = round(trip_data["planned_distance_km"] * DEMO_ACTUAL_DISTANCE_FACTOR, 1)

    if trip_data.get("planned_delivery_time") is not None:
        trip_data["actual_delivery_time"] = trip_data["planned_delivery_time"] + timedelta(
            minutes=DEMO_ACTUAL_DELIVERY_OFFSET_MINUTES
        )

    trip = Trip(trip_id=_generate_trip_id(), status="scheduled", **trip_data)
    db.add(trip)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateIdError(f"Trip {trip.trip_id} already exists") from exc
    db.refresh(trip)
    return trip


def _stop_count_subquery():
    return (
        select(func.count(RouteStop.stop_id))
        .join(Route, RouteStop.route_id == Route.route_id)
        .where(Route.trip_id == Trip.trip_id)
        .correlate(Trip)
        .scalar_subquery()
    )


def get_trip(db: Session, trip_id: str) -> Trip | None:
    row = db.query(Trip, _stop_count_subquery().label("stop_count")).filter(Trip.trip_id == trip_id).first()
    if not row:
        return None
    trip, stop_count = row

    if _apply_auto_status_transition(trip, datetime.now(timezone.utc)):
        db.add(trip)
        db.commit()
        db.refresh(trip)

    trip.stop_count = stop_count or 0
    return trip


def list_trips(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    status: str | None = None,
    driver: str | None = None,
    pickup_date: date | None = None,
) -> list[Trip]:
    stop_count_subq = _stop_count_subquery()

    query = db.query(Trip, stop_count_subq.label("stop_count"))

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Trip.trip_id.ilike(pattern),
                Trip.origin.ilike(pattern),
                Trip.destination.ilike(pattern),
                Trip.driver_name.ilike(pattern),
                Trip.vehicle_id.ilike(pattern),
            )
        )

    if status:
        query = query.filter(func.lower(Trip.status) == status.lower())

    if driver:
        query = query.filter(Trip.driver_name == driver)

    if pickup_date:
        query = query.filter(func.date(Trip.pickup_time) == pickup_date)

    rows = query.order_by(Trip.pickup_time.desc()).offset(skip).limit(limit).all()

    now = datetime.now(timezone.utc)
    trips = []
    any_changed = False
    for trip, stop_count in rows:
        if _apply_auto_status_transition(trip, now):
            db.add(trip)
            any_changed = True
        trip.stop_count = stop_count or 0
        trips.append(trip)

    if any_changed:
        db.commit()

    return trips


def get_filter_options(db: Session) -> TripFilterOptions:
    statuses = [
        s for (s,) in db.query(Trip.status).filter(Trip.status.isnot(None)).distinct().order_by(Trip.status).all()
    ]
    drivers = [
        d
        for (d,) in db.query(Trip.driver_name)
        .filter(Trip.driver_name.isnot(None))
        .distinct()
        .order_by(Trip.driver_name)
        .all()
    ]
    return TripFilterOptions(statuses=statuses, drivers=drivers)


def update_trip_status(db: Session, trip: Trip, status: str) -> Trip:
    trip.status = status
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


def complete_trip(db: Session, trip: Trip, outcome_in: TripOutcomeUpdate) -> Trip:
    """Records the real outcome once a trip finishes. status ("Delivered" or
    "Delayed") is what future driver/vehicle/route delay-rate history features
    are computed from - without it, delay_prediction_service's rolling stats
    stay empty for this trip."""
    trip.status = outcome_in.status
    trip.delay_minutes = outcome_in.delay_minutes
    trip.actual_delivery_time = outcome_in.actual_delivery_time or datetime.utcnow()
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


def get_latest_trip_by_gps_activity(db: Session) -> Trip | None:
    """The vehicle whose telemetry most recently updated - i.e. the entry
    point of the New GPS Data -> Supabase -> Fetch Latest Trip pipeline step."""
    latest_status = (
        db.query(RealtimeFleetStatus)
        .filter(RealtimeFleetStatus.current_trip_id.isnot(None))
        .order_by(RealtimeFleetStatus.last_updated.desc())
        .first()
    )
    if latest_status is None:
        return None
    return db.get(Trip, latest_status.current_trip_id)
