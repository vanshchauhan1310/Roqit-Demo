from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleRead

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.post("", response_model=VehicleRead, status_code=201)
def create_vehicle(vehicle_in: VehicleCreate, db: Session = Depends(get_db)):
    vehicle = Vehicle(**vehicle_in.model_dump())
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Vehicle {vehicle_in.vehicle_id} already exists")
    db.refresh(vehicle)
    return vehicle


@router.get("", response_model=list[VehicleRead])
def list_vehicles(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Vehicle).offset(skip).limit(limit).all()
