from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.schemas.roster import DriverRosterItem, VehicleRosterItem

# Service-due-soon threshold: flagged once the vehicle is within this many km of its next service.
SERVICE_DUE_SOON_KM = 2000

# A driver's license counts as "expiring soon" within this many days.
LICENSE_EXPIRING_SOON_DAYS = 90

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _is_license_expiring_soon(license_expiry: str | None) -> bool | None:
    expiry_date = _parse_date(license_expiry)
    if expiry_date is None:
        return None
    return (expiry_date - date.today()).days <= LICENSE_EXPIRING_SOON_DAYS


def get_driver_roster(db: Session) -> list[DriverRosterItem]:
    on_trip_driver_ids = {
        driver_id
        for (driver_id,) in db.query(Trip.driver_id)
        .filter(Trip.driver_id.isnot(None))
        .filter(func.lower(Trip.status) == "in-transit")
        .distinct()
        .all()
    }

    drivers = db.query(Driver).order_by(Driver.driver_name).all()

    return [
        DriverRosterItem(
            driver_id=d.driver_id,
            driver_name=d.driver_name,
            phone=str(d.phone) if d.phone is not None else None,
            license_type=d.license_type,
            license_expiry=d.license_expiry,
            experience_years=d.experience_years,
            base_location=d.base_location,
            rating=d.rating,
            status=d.status,
            is_on_trip=d.driver_id in on_trip_driver_ids,
            license_expiring_soon=_is_license_expiring_soon(d.license_expiry),
        )
        for d in drivers
    ]


def get_vehicle_roster(db: Session) -> list[VehicleRosterItem]:
    realtime_by_vehicle = {r.vehicle_id: r for r in db.query(RealtimeFleetStatus).all()}
    vehicles = db.query(Vehicle).order_by(Vehicle.vehicle_id).all()

    result = []
    for v in vehicles:
        realtime = realtime_by_vehicle.get(v.vehicle_id)
        is_on_trip = bool(realtime and realtime.current_trip_id)

        service_due_soon = None
        if v.next_service_due_km is not None and v.odometer_km is not None:
            service_due_soon = (v.next_service_due_km - v.odometer_km) <= SERVICE_DUE_SOON_KM

        result.append(
            VehicleRosterItem(
                vehicle_id=v.vehicle_id,
                vehicle_type=v.vehicle_type,
                make=v.make,
                model=v.model,
                year=v.year,
                fuel_type=v.fuel_type,
                load_capacity_kg=v.load_capacity_kg,
                avg_kmpl_rated=v.avg_kmpl_rated,
                base_location=v.base_location,
                status=v.status,
                is_on_trip=is_on_trip,
                service_due_soon=service_due_soon,
            )
        )
    return result
