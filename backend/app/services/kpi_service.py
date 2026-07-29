from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.schemas.report import TripKpiSummary


def get_trip_kpi_summary(db: Session) -> TripKpiSummary:
    total = db.query(Trip).count()
    completed = db.query(Trip).filter(Trip.status == "completed").count()
    in_progress = db.query(Trip).filter(Trip.status == "in_progress").count()
    cancelled = db.query(Trip).filter(Trip.status == "cancelled").count()
    on_time_rate = (completed / total) if total else None

    return TripKpiSummary(
        total_trips=total,
        completed_trips=completed,
        in_progress_trips=in_progress,
        cancelled_trips=cancelled,
        on_time_rate=on_time_rate,
    )
