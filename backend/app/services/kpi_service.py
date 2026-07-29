from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.schemas.report import TripKpiSummary


def get_trip_kpi_summary(db: Session) -> TripKpiSummary:
    total = db.query(Trip).count()
    delivered = db.query(Trip).filter(Trip.status == "Delivered").count()
    delayed = db.query(Trip).filter(Trip.status == "Delayed").count()
    in_progress = db.query(Trip).filter(Trip.status == "In-Transit").count()
    cancelled = db.query(Trip).filter(Trip.status == "Cancelled").count()

    completed = delivered + delayed
    on_time_rate = (delivered / completed) if completed else None

    return TripKpiSummary(
        total_trips=total,
        completed_trips=completed,
        in_progress_trips=in_progress,
        cancelled_trips=cancelled,
        on_time_rate=on_time_rate,
    )
