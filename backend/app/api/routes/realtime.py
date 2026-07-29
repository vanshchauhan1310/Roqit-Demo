import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.gps_breadcrumb import GpsBreadcrumb

router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.get("/trips/{trip_id}/breadcrumbs")
def get_trip_breadcrumbs(trip_id: uuid.UUID, db: Session = Depends(get_db)):
    breadcrumbs = (
        db.query(GpsBreadcrumb)
        .filter(GpsBreadcrumb.trip_id == trip_id)
        .order_by(GpsBreadcrumb.recorded_at.desc())
        .limit(500)
        .all()
    )
    return breadcrumbs
