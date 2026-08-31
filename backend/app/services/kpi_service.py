from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.schemas.report import DelayBucket, StatusBucket, TripKpiDetail, TripKpiSummary


def get_trip_kpi_summary(db: Session) -> TripKpiSummary:
    status = func.lower(Trip.status)

    total_trips, active_trips, delayed_trips, delivered_trips, on_time_delivered, avg_delay, avg_margin = db.query(
        func.count(Trip.trip_id),
        func.sum(case((status == "in-transit", 1), else_=0)),
        func.sum(case((status == "delayed", 1), else_=0)),
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


def get_trip_kpi_detail(db: Session) -> TripKpiDetail:
    """The summary plus status/delay breakdowns for the Reporting & KPI tab."""
    summary = get_trip_kpi_summary(db)

    status_rows = (
        db.query(Trip.status, func.count(Trip.trip_id))
        .filter(Trip.status.isnot(None))
        .group_by(Trip.status)
        .order_by(func.count(Trip.trip_id).desc())
        .all()
    )
    status_distribution = [StatusBucket(status=status, count=count) for status, count in status_rows]

    # Delay buckets over resolved trips (Delivered/Delayed) — "On time" means
    # either no delay recorded or zero delay minutes.
    delay_rows = (
        db.query(Trip.delay_minutes)
        .filter(func.lower(Trip.status).in_(("delivered", "delayed")))
        .all()
    )
    buckets = {"On time": 0, "≤30m": 0, "31–60m": 0, "61–90m": 0, ">90m": 0}
    for (delay_minutes,) in delay_rows:
        if delay_minutes is None or delay_minutes <= 0:
            buckets["On time"] += 1
        elif delay_minutes <= 30:
            buckets["≤30m"] += 1
        elif delay_minutes <= 60:
            buckets["31–60m"] += 1
        elif delay_minutes <= 90:
            buckets["61–90m"] += 1
        else:
            buckets[">90m"] += 1
    delay_buckets = [DelayBucket(label=label, count=count) for label, count in buckets.items()]

    return TripKpiDetail(
        **summary.model_dump(),
        status_distribution=status_distribution,
        delay_buckets=delay_buckets,
    )
