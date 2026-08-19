from pydantic import BaseModel


class VehicleSummary(BaseModel):
    vehicle_id: str
    vehicle_type: str | None
    make: str | None
    model: str | None
    year: int | None
    fuel_type: str | None
    status: str | None
    assigned: bool  # RealtimeFleetStatus.current_trip_id is non-null
    odometer_km: int | None


class LoadCapacity(BaseModel):
    load_capacity_kg: int | None
    load_weight_kg: float | None  # this trip's load
    utilization_pct: float | None


class FuelEfficiencyComparison(BaseModel):
    # All 4 expressed in liters for this trip's distance, so they're directly comparable as bars.
    this_trip_fuel_l: float | None  # trip.fuel_consumed_l only - filled by driver at trip end
    this_trip_fuel_l_is_estimate: bool
    predicted_fuel_l: float | None  # fuel_l_xgboost_v1.pkl via fuel_cost_service
    rated_fuel_l: float | None  # distance / vehicle.avg_kmpl_rated
    fleet_avg_fuel_l: float | None  # distance / fleet-wide avg_kmpl_rated for the same vehicle_type


class MaintenanceEventRead(BaseModel):
    event_id: str
    event_date: str | None
    maintenance_type: str | None
    description: str | None
    downtime_hours: float | None
    cost: float | None
    odometer_at_service: int | None


class MaintenanceStatus(BaseModel):
    last_service_date: str | None
    next_service_due_km: int | None
    pct_interval_consumed: float | None  # (odometer_km - odometer_at_last_service) / (next_service_due_km - odometer_at_last_service)
    status: str | None  # "ok" | "needs_attention" (>90%) | "overdue" (>100%) - None if pct unknown
    history: list[MaintenanceEventRead]


class CostSnapshot(BaseModel):
    # Real recorded values where the trip has resolved and Trip.fuel_cost/maintenance_cost/toll_cost
    # were actually filled in; otherwise each falls back to a clearly-labeled estimate below.
    fuel_cost: float | None
    maintenance_cost: float | None
    toll_cost: float | None

    fuel_cost_is_estimate: bool
    maintenance_cost_is_estimate: bool
    toll_cost_is_estimate: bool

    trip_tco: float | None  # sum of the 3 above (real or estimated) - maintenance_cost here is the WHOLE trip's cost, not per-km
    trip_cost_per_km: float | None
    fleet_avg_cost_per_km: float | None  # avg (fuel+maintenance+toll)/actual_distance_km across resolved trips fleet-wide


class VehicleIntelligenceRead(BaseModel):
    vehicle: VehicleSummary
    load: LoadCapacity
    fuel_efficiency: FuelEfficiencyComparison
    maintenance: MaintenanceStatus
    cost: CostSnapshot
