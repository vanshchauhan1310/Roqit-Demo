from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.roster import DriverRosterItem, VehicleRosterItem
from app.services import roster_service

router = APIRouter(prefix="/roster", tags=["roster"])


@router.get("/drivers", response_model=list[DriverRosterItem])
def list_driver_roster(db: Session = Depends(get_db)):
    return roster_service.get_driver_roster(db)


@router.get("/vehicles", response_model=list[VehicleRosterItem])
def list_vehicle_roster(db: Session = Depends(get_db)):
    return roster_service.get_vehicle_roster(db)
