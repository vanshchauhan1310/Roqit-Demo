import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.trip import TripCreate, TripRead, TripUpdateStatus
from app.services import trip_service

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripRead, status_code=201)
def create_trip(trip_in: TripCreate, db: Session = Depends(get_db)):
    return trip_service.create_trip(db, trip_in)


@router.get("", response_model=list[TripRead])
def list_trips(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return trip_service.list_trips(db, skip, limit)


@router.get("/{trip_id}", response_model=TripRead)
def get_trip(trip_id: uuid.UUID, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.patch("/{trip_id}/status", response_model=TripRead)
def update_trip_status(trip_id: uuid.UUID, status_in: TripUpdateStatus, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip_service.update_trip_status(db, trip, status_in.status)
