from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.report import TripKpiSummary
from app.services import kpi_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/trips/kpi-summary", response_model=TripKpiSummary)
def trip_kpi_summary(db: Session = Depends(get_db)):
    return kpi_service.get_trip_kpi_summary(db)
