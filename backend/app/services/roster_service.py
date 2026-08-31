from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.route import Route
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.models.dispatch_config import VehicleDispatchConfig
from app.models.hub import Hub
from app.schemas.roster import DriverRosterItem, VehicleRosterItem

# Service-due-soon threshold: flagged once the vehicle is within this many km of its next service.
SERVICE_DUE_SOON_KM = 2000

# A driver's license counts as "expiring soon" within this many days.
LICENSE_EXPIRING_SOON_DAYS = 90

# Route statuses that mean the driver/vehicle is actively assigned (not available for new work)
ACTIVE_ROUTE_STATUSES = {"planned", "scheduled", "in-transit"}

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


def _get_active_route_for_driver(db: Session, driver_id: str) -> Route | None:
    """Get the active route (planned/scheduled/in-transit) assigned to this driver, if any."""
    return (
        db.query(Route)
        .filter(Route.driver_id == driver_id)
        .filter(Route.status.in_(ACTIVE_ROUTE_STATUSES))
        .order_by(Route.pickup_time.asc().nullslast())
        .first()
    )


def _get_active_route_for_vehicle(db: Session, vehicle_id: str) -> Route | None:
    """Get the active route (planned/scheduled/in-transit) assigned to this vehicle, if any."""
    return (
        db.query(Route)
        .filter(Route.vehicle_id == vehicle_id)
        .filter(Route.status.in_(ACTIVE_ROUTE_STATUSES))
        .order_by(Route.pickup_time.asc().nullslast())
        .first()
    )


def _compute_driver_assignment(driver: Driver, active_route: Route | None) -> tuple[str, str | None, str | None, datetime | None, datetime | None]:
    """Compute assignment status and current route details for a driver.
    Returns: (assignment_status, current_route_id, current_route_name, current_route_pickup_time, current_route_planned_delivery_time)
    """
    if active_route:
        return (
            "assigned",
            str(active_route.route_id),
            active_route.name,
            active_route.pickup_time,
            active_route.planned_delivery_time,
        )
    
    # Check if driver is marked as unavailable (e.g., off-duty, inactive)
    if driver.status and driver.status.lower() in ("off-duty", "inactive", "unavailable", "suspended"):
        return ("unavailable", None, None, None, None)
    
    return ("available", None, None, None, None)


def _compute_vehicle_assignment(vehicle: Vehicle, active_route: Route | None) -> tuple[str, str | None, str | None, datetime | None, datetime | None]:
    """Compute assignment status and current route details for a vehicle.
    Returns: (assignment_status, current_route_id, current_route_name, current_route_pickup_time, current_route_planned_delivery_time)
    """
    if active_route:
        return (
            "assigned",
            str(active_route.route_id),
            active_route.name,
            active_route.pickup_time,
            active_route.planned_delivery_time,
        )
    
    # Check if vehicle is marked as unavailable (e.g., maintenance, retired)
    if vehicle.status and vehicle.status.lower() in ("maintenance", "retired", "inactive", "unavailable", "out-of-service"):
        return ("unavailable", None, None, None, None)
    
    return ("available", None, None, None, None)


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

    result = []
    for d in drivers:
        active_route = _get_active_route_for_driver(db, d.driver_id)
        assignment_status, current_route_id, current_route_name, current_route_pickup_time, current_route_planned_delivery_time = _compute_driver_assignment(d, active_route)
        
        result.append(
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
                assignment_status=assignment_status,
                current_route_id=current_route_id,
                current_route_name=current_route_name,
                current_route_pickup_time=current_route_pickup_time,
                current_route_planned_delivery_time=current_route_planned_delivery_time,
            )
        )
    return result


def get_vehicle_roster(db: Session) -> list[VehicleRosterItem]:
    realtime_by_vehicle = {r.vehicle_id: r for r in db.query(RealtimeFleetStatus).all()}
    vehicles = db.query(Vehicle).order_by(Vehicle.vehicle_id).all()
    configs_by_vehicle = {config.vehicle_id: config for config in db.query(VehicleDispatchConfig).all()}
    hub_ids = {config.base_hub_id for config in configs_by_vehicle.values() if config.base_hub_id}
    hubs_by_id = {hub.hub_id: hub for hub in db.query(Hub).filter(Hub.hub_id.in_(hub_ids)).all()} if hub_ids else {}

    result = []
    for v in vehicles:
        realtime = realtime_by_vehicle.get(v.vehicle_id)
        is_on_trip = bool(realtime and realtime.current_trip_id)

        service_due_soon = None
        if v.next_service_due_km is not None and v.odometer_km is not None:
            service_due_soon = (v.next_service_due_km - v.odometer_km) <= SERVICE_DUE_SOON_KM

        active_route = _get_active_route_for_vehicle(db, v.vehicle_id)
        assignment_status, current_route_id, current_route_name, current_route_pickup_time, current_route_planned_delivery_time = _compute_vehicle_assignment(v, active_route)
        config = configs_by_vehicle.get(v.vehicle_id)
        hub = hubs_by_id.get(config.base_hub_id) if config and config.base_hub_id else None

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
                hub_name=hub.name if hub else None,
                status=v.status,
                is_on_trip=is_on_trip,
                service_due_soon=service_due_soon,
                assignment_status=assignment_status,
                current_route_id=current_route_id,
                current_route_name=current_route_name,
                current_route_pickup_time=current_route_pickup_time,
                current_route_planned_delivery_time=current_route_planned_delivery_time,
            )
        )
    return result
