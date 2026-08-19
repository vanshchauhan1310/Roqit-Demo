from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TripBase(BaseModel):
    trip_id: str
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_type: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    gps_start_lat: Optional[float] = None
    gps_start_lon: Optional[float] = None
    gps_end_lat: Optional[float] = None
    gps_end_lon: Optional[float] = None
    planned_distance_km: Optional[float] = None
    actual_distance_km: Optional[float] = None
    pickup_time: Optional[datetime] = None
    planned_delivery_time: Optional[datetime] = None
    actual_delivery_time: Optional[datetime] = None
    delay_minutes: Optional[int] = None
    status: Optional[str] = None
    is_delayed: Optional[bool] = None
    weather_condition: Optional[str] = None
    road_type: Optional[str] = None
    traffic_density: Optional[str] = None
    odometer_start: Optional[int] = None
    odometer_end: Optional[int] = None
    fuel_consumed_l: Optional[float] = None
    fuel_price_per_l: Optional[float] = None
    fuel_cost: Optional[float] = None
    driver_pay: Optional[float] = None
    maintenance_cost: Optional[float] = None
    toll_cost: Optional[float] = None
    idle_time_min: Optional[int] = None
    load_weight_kg: Optional[int] = None
    load_value: Optional[float] = None
    profit_margin: Optional[float] = None
    violation_count: Optional[int] = None
    speeding_incidents: Optional[int] = None
    harsh_braking_count: Optional[int] = None
    harsh_accel_count: Optional[int] = None
    stop_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class TripResponse(TripBase):
    pass


# Alias kept for the route/service layer, which was written against this name.
TripRead = TripResponse


class TripUpdateStatus(BaseModel):
    status: str


class TripOutcomeUpdate(BaseModel):
    """Records the real outcome once a trip finishes - status drives is_delayed
    (status == "Delayed"), which future driver/vehicle/route history features
    are computed from."""

    status: str  # "Delivered" or "Delayed"
    delay_minutes: Optional[int] = None
    actual_delivery_time: Optional[datetime] = None


class TripFilterOptions(BaseModel):
    statuses: list[str]
    drivers: list[str]


class TripCreate(BaseModel):
    """A Trip is now just a single pickup + single drop (origin/destination) —
    driver, vehicle, and pickup_time are assigned later at the Route level
    (RouteAssignRequest) once this trip is grouped with others into a route."""

    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_type: Optional[str] = None
    origin: str
    destination: str
    gps_start_lat: Optional[float] = None
    gps_start_lon: Optional[float] = None
    gps_end_lat: Optional[float] = None
    gps_end_lon: Optional[float] = None
    planned_distance_km: Optional[float] = None
    pickup_time: Optional[datetime] = None
    planned_delivery_time: Optional[datetime] = None
    load_weight_kg: Optional[int] = None
    load_value: Optional[float] = None
    weather_condition: Optional[str] = None
    road_type: Optional[str] = None
    traffic_density: Optional[str] = None
    fuel_price_per_l: Optional[float] = None
