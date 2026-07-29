from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.driver import Driver
from app.schemas.driver import DriverCreate, DriverRead

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("", response_model=DriverRead, status_code=201)
def create_driver(driver_in: DriverCreate, db: Session = Depends(get_db)):
    driver = Driver(**driver_in.model_dump())
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@router.get("", response_model=list[DriverRead])
def list_drivers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Driver).offset(skip).limit(limit).all()
