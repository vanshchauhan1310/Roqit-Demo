from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.gps_breadcrumb import GpsBreadcrumb
from app.schemas.gps_breadcrumb import GpsBreadcrumbRead
from app.schemas.realtime import RealtimeLiveRead
from app.services import realtime_service, trip_service

router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.get("/trips/{trip_id}/breadcrumbs", response_model=list[GpsBreadcrumbRead])
def get_trip_breadcrumbs(trip_id: str, db: Session = Depends(get_db)):
    return (
        db.query(GpsBreadcrumb)
        .filter(GpsBreadcrumb.trip_id == trip_id)
        .order_by(GpsBreadcrumb.timestamp.asc())
        .limit(500)
        .all()
    )


@router.get("/trips/{trip_id}/live", response_model=RealtimeLiveRead)
def get_trip_live_status(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return realtime_service.get_live_status(db, trip)
