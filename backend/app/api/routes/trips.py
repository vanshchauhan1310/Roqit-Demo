from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.trip import TripCreate, TripFilterOptions, TripOutcomeUpdate, TripRead, TripUpdateStatus
from app.services import trip_service

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripRead, status_code=201)
def create_trip(trip_in: TripCreate, db: Session = Depends(get_db)):
    try:
        return trip_service.create_trip(db, trip_in)
    except trip_service.DuplicateIdError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=list[TripRead])
def list_trips(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    status: str | None = None,
    driver: str | None = None,
    pickup_date: date | None = None,
    db: Session = Depends(get_db),
):
    return trip_service.list_trips(db, skip, limit, search, status, driver, pickup_date)


@router.get("/filter-options", response_model=TripFilterOptions)
def get_filter_options(db: Session = Depends(get_db)):
    return trip_service.get_filter_options(db)


@router.get("/{trip_id}", response_model=TripRead)
def get_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.patch("/{trip_id}/status", response_model=TripRead)
def update_trip_status(trip_id: str, status_in: TripUpdateStatus, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip_service.update_trip_status(db, trip, status_in.status)


@router.patch("/{trip_id}/outcome", response_model=TripRead)
def complete_trip(trip_id: str, outcome_in: TripOutcomeUpdate, db: Session = Depends(get_db)):
    """Records the real delay outcome once a trip finishes, feeding future
    driver/vehicle/route history features used by /predictions/delay."""
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip_service.complete_trip(db, trip, outcome_in)
