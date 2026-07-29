from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.trip import Trip
from app.schemas.trip import TripCreate, TripOutcomeUpdate


class DuplicateIdError(ValueError):
    pass


def create_trip(db: Session, trip_in: TripCreate) -> Trip:
    trip = Trip(**trip_in.model_dump())
    db.add(trip)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateIdError(f"Trip {trip_in.trip_id} already exists") from exc
    db.refresh(trip)
    return trip


def get_trip(db: Session, trip_id: str) -> Trip | None:
    return db.get(Trip, trip_id)


def list_trips(db: Session, skip: int = 0, limit: int = 100) -> list[Trip]:
    return db.query(Trip).order_by(Trip.pickup_time.desc()).offset(skip).limit(limit).all()


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
