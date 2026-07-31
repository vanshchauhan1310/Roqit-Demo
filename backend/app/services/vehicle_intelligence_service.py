from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.maintenance_event import MaintenanceEvent
from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.schemas.vehicle_intelligence import (
    CostSnapshot,
    FuelEfficiencyComparison,
    LoadCapacity,
    MaintenanceEventRead,
    MaintenanceStatus,
    VehicleIntelligenceRead,
    VehicleSummary,
)

# Resolved trips only - fuel/cost/distance figures are only meaningful once a
# trip has actually completed and its actuals were recorded.
_RESOLVED_STATUSES = ("delivered", "delayed")


def _build_vehicle_summary(vehicle: Vehicle, db: Session) -> VehicleSummary:
    fleet_status = db.get(RealtimeFleetStatus, vehicle.vehicle_id)
    assigned = bool(fleet_status and fleet_status.current_trip_id)
    return VehicleSummary(
        vehicle_id=vehicle.vehicle_id,
        vehicle_type=vehicle.vehicle_type,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        fuel_type=vehicle.fuel_type,
        status=vehicle.status,
        assigned=assigned,
        odometer_km=vehicle.odometer_km,
    )


def _build_load_capacity(vehicle: Vehicle, trip: Trip) -> LoadCapacity:
    utilization_pct = None
    if trip.load_weight_kg is not None and vehicle.load_capacity_kg:
        utilization_pct = round((trip.load_weight_kg / vehicle.load_capacity_kg) * 100, 1)
    return LoadCapacity(
        load_capacity_kg=vehicle.load_capacity_kg,
        load_weight_kg=trip.load_weight_kg,
        utilization_pct=utilization_pct,
    )


def _build_fuel_efficiency(db: Session, vehicle: Vehicle, trip: Trip) -> FuelEfficiencyComparison:
    this_trip_kmpl = None
    if trip.actual_distance_km and trip.fuel_consumed_l:
        this_trip_kmpl = round(trip.actual_distance_km / trip.fuel_consumed_l, 2)

    fleet_avg_kmpl = None
    if vehicle.vehicle_type:
        avg = (
            db.query(func.avg(Vehicle.avg_kmpl_rated))
            .filter(Vehicle.vehicle_type == vehicle.vehicle_type, Vehicle.avg_kmpl_rated.isnot(None))
            .scalar()
        )
        fleet_avg_kmpl = round(avg, 2) if avg is not None else None

    return FuelEfficiencyComparison(
        this_trip_kmpl=this_trip_kmpl,
        rated_kmpl=vehicle.avg_kmpl_rated,
        fleet_avg_kmpl=fleet_avg_kmpl,
    )


def _build_maintenance_status(db: Session, vehicle: Vehicle) -> MaintenanceStatus:
    events = (
        db.query(MaintenanceEvent)
        .filter(MaintenanceEvent.vehicle_id == vehicle.vehicle_id)
        .order_by(MaintenanceEvent.event_date.desc())
        .all()
    )

    pct_interval_consumed = None
    last_service_odometer = events[0].odometer_at_service if events else None
    if (
        last_service_odometer is not None
        and vehicle.odometer_km is not None
        and vehicle.next_service_due_km is not None
        and vehicle.next_service_due_km > last_service_odometer
    ):
        pct_interval_consumed = round(
            ((vehicle.odometer_km - last_service_odometer) / (vehicle.next_service_due_km - last_service_odometer))
            * 100,
            1,
        )

    return MaintenanceStatus(
        last_service_date=vehicle.last_service_date,
        next_service_due_km=vehicle.next_service_due_km,
        pct_interval_consumed=pct_interval_consumed,
        history=[
            MaintenanceEventRead(
                event_id=e.event_id,
                event_date=e.event_date,
                maintenance_type=e.maintenance_type,
                description=e.description,
                downtime_hours=e.downtime_hours,
                cost=e.cost,
                odometer_at_service=e.odometer_at_service,
            )
            for e in events
        ],
    )


def _build_cost_snapshot(db: Session, trip: Trip) -> CostSnapshot:
    trip_tco = None
    trip_cost_per_km = None
    if trip.fuel_cost is not None and trip.maintenance_cost is not None and trip.toll_cost is not None:
        trip_tco = round(trip.fuel_cost + trip.maintenance_cost + trip.toll_cost, 2)
        if trip.actual_distance_km:
            trip_cost_per_km = round(trip_tco / trip.actual_distance_km, 2)

    fleet_costs = (
        db.query(Trip.fuel_cost, Trip.maintenance_cost, Trip.toll_cost, Trip.actual_distance_km)
        .filter(
            func.lower(Trip.status).in_(_RESOLVED_STATUSES),
            Trip.fuel_cost.isnot(None),
            Trip.maintenance_cost.isnot(None),
            Trip.toll_cost.isnot(None),
            Trip.actual_distance_km.isnot(None),
            Trip.actual_distance_km > 0,
        )
        .all()
    )
    per_km_costs = [
        (fuel + maint + toll) / dist for fuel, maint, toll, dist in fleet_costs if dist
    ]
    fleet_avg_cost_per_km = round(sum(per_km_costs) / len(per_km_costs), 2) if per_km_costs else None

    return CostSnapshot(
        fuel_cost=trip.fuel_cost,
        maintenance_cost=trip.maintenance_cost,
        toll_cost=trip.toll_cost,
        trip_tco=trip_tco,
        trip_cost_per_km=trip_cost_per_km,
        fleet_avg_cost_per_km=fleet_avg_cost_per_km,
    )


def get_vehicle_intelligence(db: Session, trip: Trip) -> VehicleIntelligenceRead | None:
    vehicle = trip.vehicle
    if vehicle is None:
        return None

    return VehicleIntelligenceRead(
        vehicle=_build_vehicle_summary(vehicle, db),
        load=_build_load_capacity(vehicle, trip),
        fuel_efficiency=_build_fuel_efficiency(db, vehicle, trip),
        maintenance=_build_maintenance_status(db, vehicle),
        cost=_build_cost_snapshot(db, trip),
    )
