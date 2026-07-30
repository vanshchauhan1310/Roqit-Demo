from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.schemas.report import TripKpiSummary


def get_trip_kpi_summary(db: Session) -> TripKpiSummary:
    status = func.lower(Trip.status)

    total_trips, active_trips, delayed_trips, delivered_trips, on_time_delivered, avg_delay, avg_margin = db.query(
        func.count(Trip.trip_id),
        func.sum(case((status == "in-transit", 1), else_=0)),
        func.sum(case((status == "delayed", 1), (Trip.delay_minutes > 0, 1), else_=0)),
        func.sum(case((status == "delivered", 1), else_=0)),
        func.sum(case((status == "delivered", case((Trip.delay_minutes.is_(None), 1), (Trip.delay_minutes <= 0, 1), else_=0)), else_=0)),
        func.avg(case((Trip.delay_minutes > 0, Trip.delay_minutes))),
        func.avg(Trip.profit_margin),
    ).one()

    total_trips = total_trips or 0
    delivered_trips = delivered_trips or 0

    return TripKpiSummary(
        total_trips=total_trips,
        active_trips=active_trips or 0,
        delayed_trips=delayed_trips or 0,
        on_time_rate=(on_time_delivered / delivered_trips) if delivered_trips else None,
        avg_delay_minutes=float(avg_delay) if avg_delay is not None else None,
        avg_profit_margin=float(avg_margin) if avg_margin is not None else None,
    )
