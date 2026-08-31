import hashlib
import asyncio

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.maintenance_event import MaintenanceEvent
from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.route import RouteStop
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
from app.services import fuel_cost_service

# Resolved trips only - fuel/cost/distance figures are only meaningful once a
# trip has actually completed and its actuals were recorded.
_RESOLVED_STATUSES = ("delivered", "delayed")

# Maintenance-interval badge thresholds, matching the progress bar shown in the UI.
_NEEDS_ATTENTION_THRESHOLD_PCT = 90
_OVERDUE_THRESHOLD_PCT = 100

# Demo-only: there's no live toll feed wired in, so toll cost is a hand-coded
# per-km rate with a deterministic per-trip multiplier (derived from the trip_id
# hash, not random) so it varies trip-to-trip the way a real toll route would.
TOLL_COST_PER_KM_INR = 2.0

# Demo-only: no live fuel-price feed yet, so fuel cost is estimated from the
# vehicle's rated efficiency (distance / avg_kmpl_rated) at this fixed price.
FUEL_PRICE_PER_L_INR = 90.0


def _build_vehicle_summary(vehicle: Vehicle, db: Session, trip: Trip) -> VehicleSummary:
    fleet_status = db.get(RealtimeFleetStatus, vehicle.vehicle_id)
    assigned = bool(fleet_status and fleet_status.current_trip_id) or trip.vehicle_id == vehicle.vehicle_id
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


async def _predict_fuel_liters(trip: Trip) -> float | None:
    try:
        result = await fuel_cost_service.predict_fuel_liters_for_trip(trip)
        return result["predicted_fuel_liters"]
    except (
        fuel_cost_service.MissingFeatureDataError,
        fuel_cost_service.UnsupportedCategoryError,
        fuel_cost_service.InvalidFeatureRangeError,
    ):
        return None


async def _average_route_predicted_fuel_liters(db: Session, trip: Trip) -> float | None:
    """Average successful ML fuel forecasts for the trip's planned route.

    A route can contain several independently modelled consignments. Showing
    just the selected row's prediction makes the route-level intelligence card
    depend on which trip was opened, so aggregate the available predictions.
    An ungrouped trip naturally falls back to its own prediction.
    """
    route_id = (
        db.query(RouteStop.route_id)
        .filter(RouteStop.trip_id == trip.trip_id)
        .order_by(RouteStop.sequence)
        .first()
    )
    if route_id is None:
        return await _predict_fuel_liters(trip)

    route_trip_ids = [
        trip_id
        for (trip_id,) in db.query(RouteStop.trip_id)
        .filter(RouteStop.route_id == route_id[0], RouteStop.trip_id.isnot(None))
        .distinct()
        .all()
    ]
    route_trips = db.query(Trip).filter(Trip.trip_id.in_(route_trip_ids)).all()
    predictions = await asyncio.gather(*(_predict_fuel_liters(route_trip) for route_trip in route_trips))
    available = [prediction for prediction in predictions if prediction is not None]
    return sum(available) / len(available) if available else None


def _build_fuel_efficiency(
    db: Session, vehicle: Vehicle, trip: Trip, predicted_fuel_liters: float | None
) -> FuelEfficiencyComparison:
    distance = trip.actual_distance_km or trip.planned_distance_km

    fleet_avg_kmpl = None
    if vehicle.vehicle_type:
        avg = (
            db.query(func.avg(Vehicle.avg_kmpl_rated))
            .filter(Vehicle.vehicle_type == vehicle.vehicle_type, Vehicle.avg_kmpl_rated.isnot(None))
            .scalar()
        )
        fleet_avg_kmpl = round(avg, 2) if avg is not None else None

    # "This trip (actual)" only fills once the driver records the fuel
    # consumed at the end of the trip - no estimate fallback, because the
    # rated figure below already covers what this vehicle should have used.
    this_trip_fuel_l = trip.fuel_consumed_l
    this_trip_fuel_l_is_estimate = False

    return FuelEfficiencyComparison(
        this_trip_fuel_l=round(this_trip_fuel_l, 1) if this_trip_fuel_l is not None else None,
        this_trip_fuel_l_is_estimate=this_trip_fuel_l_is_estimate,
        predicted_fuel_l=round(predicted_fuel_liters, 1) if predicted_fuel_liters is not None else None,
        rated_fuel_l=round(distance / vehicle.avg_kmpl_rated, 1) if distance and vehicle.avg_kmpl_rated else None,
        fleet_avg_fuel_l=round(distance / fleet_avg_kmpl, 1) if distance and fleet_avg_kmpl else None,
    )


def _maintenance_badge(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct > _OVERDUE_THRESHOLD_PCT:
        return "overdue"
    if pct > _NEEDS_ATTENTION_THRESHOLD_PCT:
        return "needs_attention"
    return "ok"


def _build_maintenance_status(db: Session, vehicle: Vehicle) -> tuple[MaintenanceStatus, list[MaintenanceEvent]]:
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

    status = MaintenanceStatus(
        last_service_date=vehicle.last_service_date,
        next_service_due_km=vehicle.next_service_due_km,
        pct_interval_consumed=pct_interval_consumed,
        status=_maintenance_badge(pct_interval_consumed),
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
    return status, events


def _toll_cost_estimate(trip: Trip, distance: float | None) -> float | None:
    if distance is None:
        return None
    # Deterministic 0.70-1.30x spread from the trip_id hash - not random, but
    # varies trip-to-trip the way real toll routes would.
    digest = int(hashlib.sha1(trip.trip_id.encode()).hexdigest(), 16)
    multiplier = 0.7 + (digest % 61) / 100
    return round(TOLL_COST_PER_KM_INR * distance * multiplier, 2)


def _maintenance_cost_estimate(
    db: Session, vehicle: Vehicle, events: list[MaintenanceEvent]
) -> float | None:
    """Overall maintenance cost attributable to this trip - the vehicle's own
    average cost per service event, not prorated to distance (a single
    service isn't a per-km expense the way fuel is)."""
    costs = [e.cost for e in events if e.cost is not None]
    if costs:
        return round(sum(costs) / len(costs), 2)

    # Fall back to the same-vehicle-type fleet's average event cost if this
    # vehicle has no service history yet.
    fleet_avg = (
        db.query(func.avg(MaintenanceEvent.cost))
        .join(Vehicle, Vehicle.vehicle_id == MaintenanceEvent.vehicle_id)
        .filter(Vehicle.vehicle_type == vehicle.vehicle_type, MaintenanceEvent.cost.isnot(None))
        .scalar()
    )
    return round(fleet_avg, 2) if fleet_avg is not None else None


def _build_cost_snapshot(
    db: Session,
    vehicle: Vehicle,
    trip: Trip,
    events: list[MaintenanceEvent],
) -> CostSnapshot:
    distance = trip.actual_distance_km or trip.planned_distance_km

    fuel_cost = trip.fuel_cost
    fuel_cost_is_estimate = fuel_cost is None
    if fuel_cost is None and distance and vehicle.avg_kmpl_rated:
        # Rated liters (distance / avg_kmpl_rated) at a hardcoded fuel price -
        # replaced by the driver's actual fuel cost once the trip resolves.
        fuel_cost = round((distance / vehicle.avg_kmpl_rated) * FUEL_PRICE_PER_L_INR, 2)

    toll_cost = trip.toll_cost
    toll_cost_is_estimate = toll_cost is None
    if toll_cost is None:
        toll_cost = _toll_cost_estimate(trip, distance)

    maintenance_cost = trip.maintenance_cost
    maintenance_cost_is_estimate = maintenance_cost is None
    if maintenance_cost is None:
        maintenance_cost = _maintenance_cost_estimate(db, vehicle, events)

    trip_tco = None
    trip_cost_per_km = None
    if fuel_cost is not None and maintenance_cost is not None and toll_cost is not None:
        trip_tco = round(fuel_cost + maintenance_cost + toll_cost, 2)
        if distance:
            trip_cost_per_km = round(trip_tco / distance, 2)

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
    per_km_costs = [(fuel + maint + toll) / dist for fuel, maint, toll, dist in fleet_costs if dist]
    fleet_avg_cost_per_km = round(sum(per_km_costs) / len(per_km_costs), 2) if per_km_costs else None

    return CostSnapshot(
        fuel_cost=fuel_cost,
        maintenance_cost=maintenance_cost,
        toll_cost=toll_cost,
        fuel_cost_is_estimate=fuel_cost_is_estimate,
        maintenance_cost_is_estimate=maintenance_cost_is_estimate,
        toll_cost_is_estimate=toll_cost_is_estimate,
        trip_tco=trip_tco,
        trip_cost_per_km=trip_cost_per_km,
        fleet_avg_cost_per_km=fleet_avg_cost_per_km,
    )


async def get_vehicle_intelligence(db: Session, trip: Trip) -> VehicleIntelligenceRead | None:
    vehicle = trip.vehicle
    if vehicle is None:
        return None

    predicted_fuel_liters = await _average_route_predicted_fuel_liters(db, trip)
    maintenance_status, events = _build_maintenance_status(db, vehicle)

    return VehicleIntelligenceRead(
        vehicle=_build_vehicle_summary(vehicle, db, trip),
        load=_build_load_capacity(vehicle, trip),
        fuel_efficiency=_build_fuel_efficiency(db, vehicle, trip, predicted_fuel_liters),
        maintenance=maintenance_status,
        cost=_build_cost_snapshot(db, vehicle, trip, events),
    )
