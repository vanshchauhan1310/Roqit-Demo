from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.gps_breadcrumb import GpsBreadcrumb
from app.schemas.gps_breadcrumb import GpsBreadcrumbRead

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
