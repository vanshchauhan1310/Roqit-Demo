from datetime import datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.driver_hours import DriverHours
from app.models.trip import Trip
from app.schemas.driver_intelligence import (
    DriverBehaviorRead,
    DriverHoursRead,
    DriverIntelligenceRead,
    DriverTripRead,
)
from app.services.roster_service import (
    LICENSE_EXPIRING_SOON_DAYS,
    _is_license_expiring_soon,
)

# Behavior counters only mean something once a trip has actually run.
_RESOLVED_STATUSES = ("delivered", "delayed")


def _build_hos_history(db: Session, driver_id: str) -> list[DriverHoursRead]:
    rows = (
        db.query(DriverHours)
        .filter(DriverHours.driver_id == driver_id)
        .order_by(DriverHours.date.desc())
        .limit(14)
        .all()
    )
    return [
        DriverHoursRead(
            date=h.date,
            trips_count=h.trips_count,
            hours_driven=h.hours_driven,
            rest_hours=h.rest_hours,
            hos_compliant=h.hos_compliant,
        )
        for h in rows
    ]


def get_driver_intelligence(db: Session, trip: Trip) -> DriverIntelligenceRead | None:
    if not trip.driver_id:
        return None
    driver = db.get(Driver, trip.driver_id)
    if driver is None:
        return None

    resolved = db.query(Trip).filter(
        Trip.driver_id == driver.driver_id,
        func.lower(Trip.status).in_(_RESOLVED_STATUSES),
    ).all()

    total_trips = len(resolved)
    delayed_trips = sum(1 for t in resolved if (t.delay_minutes or 0) > 0)
    on_time_trips = total_trips - delayed_trips
    delays = [t.delay_minutes for t in resolved if t.delay_minutes is not None and t.delay_minutes > 0]
    margins = [t.profit_margin for t in resolved if t.profit_margin is not None]

    behavior = DriverBehaviorRead(
        speeding_incidents=sum(t.speeding_incidents or 0 for t in resolved),
        harsh_braking_count=sum(t.harsh_braking_count or 0 for t in resolved),
        harsh_accel_count=sum(t.harsh_accel_count or 0 for t in resolved),
        violation_count=sum(t.violation_count or 0 for t in resolved),
    )

    recent = (
        db.query(Trip)
        .filter(Trip.driver_id == driver.driver_id)
        .order_by(Trip.pickup_time.desc().nullslast())
        .limit(10)
        .all()
    )

    return DriverIntelligenceRead(
        driver_id=driver.driver_id,
        driver_name=driver.driver_name,
        phone=str(driver.phone) if driver.phone is not None else None,
        license_type=driver.license_type,
        license_expiry=driver.license_expiry,
        experience_years=driver.experience_years,
        base_location=driver.base_location,
        rating=driver.rating,
        status=driver.status,
        is_on_trip=bool(trip.status and trip.status.lower() == "in-transit"),
        license_expiring_soon=_is_license_expiring_soon(driver.license_expiry),
        total_trips=total_trips,
        on_time_rate=round(on_time_trips / total_trips, 3) if total_trips else None,
        avg_delay_minutes=round(sum(delays) / len(delays), 1) if delays else None,
        avg_profit_margin=round(sum(margins) / len(margins), 2) if margins else None,
        delayed_trips=delayed_trips,
        behavior=behavior,
        hos_history=_build_hos_history(db, driver.driver_id),
        recent_trips=[
            DriverTripRead(
                trip_id=t.trip_id,
                origin=t.origin,
                destination=t.destination,
                status=t.status,
                pickup_time=t.pickup_time,
                actual_delivery_time=t.actual_delivery_time,
                delay_minutes=t.delay_minutes,
                profit_margin=t.profit_margin,
            )
            for t in recent
        ],
    )
