from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TripBase(BaseModel):
    driver_id: str | None = None
    vehicle_id: str | None = None
    driver_name: str | None = None
    vehicle_type: str | None = None
    origin: str | None = None
    destination: str | None = None

    # Planned/static attributes required by the delay-risk model's feature
    # contract (ml/feature_contract_v2.json) - these already exist as native
    # columns on the real Supabase `trips` table.
    gps_start_lat: float | None = None
    gps_start_lon: float | None = None
    gps_end_lat: float | None = None
    gps_end_lon: float | None = None
    planned_distance_km: float | None = None
    weather_condition: str | None = None
    road_type: str | None = None
    traffic_density: str | None = None
    fuel_price_per_l: float | None = None

    pickup_time: datetime | None = None
    planned_delivery_time: datetime | None = None


class TripCreate(TripBase):
    trip_id: str


class TripUpdateStatus(BaseModel):
    status: str


class TripOutcomeUpdate(BaseModel):
    """Records the real outcome once a trip finishes - status drives is_delayed
    (status == "Delayed"), which future driver/vehicle/route history features
    are computed from."""

    status: str  # "Delivered" or "Delayed"
    delay_minutes: int | None = None
    actual_delivery_time: datetime | None = None


class TripRead(TripBase):
    model_config = ConfigDict(from_attributes=True)

    trip_id: str
    status: str | None = None
    is_delayed: bool | None = None
    actual_distance_km: float | None = None
    actual_delivery_time: datetime | None = None
    delay_minutes: int | None = None
