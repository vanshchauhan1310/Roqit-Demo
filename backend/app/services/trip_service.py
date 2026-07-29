import uuid

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.schemas.trip import TripCreate


def create_trip(db: Session, trip_in: TripCreate) -> Trip:
    trip = Trip(**trip_in.model_dump())
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


def get_trip(db: Session, trip_id: uuid.UUID) -> Trip | None:
    return db.get(Trip, trip_id)


def list_trips(db: Session, skip: int = 0, limit: int = 100) -> list[Trip]:
    return db.query(Trip).order_by(Trip.created_at.desc()).offset(skip).limit(limit).all()


def update_trip_status(db: Session, trip: Trip, status: str) -> Trip:
    trip.status = status
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip
