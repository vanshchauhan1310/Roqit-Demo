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
    this_trip_kmpl: float | None  # actual_distance_km / fuel_consumed_l, only once both are known
    rated_kmpl: float | None
    fleet_avg_kmpl: float | None  # avg avg_kmpl_rated across other vehicles of the same vehicle_type


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
    history: list[MaintenanceEventRead]


class CostSnapshot(BaseModel):
    fuel_cost: float | None
    maintenance_cost: float | None
    toll_cost: float | None
    trip_tco: float | None  # sum of the 3 above, once all known
    trip_cost_per_km: float | None
    fleet_avg_cost_per_km: float | None  # avg (fuel+maintenance+toll)/actual_distance_km across resolved trips fleet-wide


class VehicleIntelligenceRead(BaseModel):
    vehicle: VehicleSummary
    load: LoadCapacity
    fuel_efficiency: FuelEfficiencyComparison
    maintenance: MaintenanceStatus
    cost: CostSnapshot
