from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DriverTripRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trip_id: str
    origin: str | None = None
    destination: str | None = None
    status: str | None = None
    pickup_time: datetime | None = None
    actual_delivery_time: datetime | None = None
    delay_minutes: int | None = None
    profit_margin: float | None = None


class DriverHoursRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: str | None = None
    trips_count: int | None = None
    hours_driven: float | None = None
    rest_hours: float | None = None
    hos_compliant: bool | None = None


class DriverBehaviorRead(BaseModel):
    speeding_incidents: int = 0
    harsh_braking_count: int = 0
    harsh_accel_count: int = 0
    violation_count: int = 0


class DriverIntelligenceRead(BaseModel):
    driver_id: str
    driver_name: str | None = None
    phone: str | None = None
    license_type: str | None = None
    license_expiry: str | None = None
    experience_years: float | None = None
    base_location: str | None = None
    rating: float | None = None
    status: str | None = None
    is_on_trip: bool
    license_expiring_soon: bool | None = None
    total_trips: int
    on_time_rate: float | None = None
    avg_delay_minutes: float | None = None
    avg_profit_margin: float | None = None
    delayed_trips: int
    behavior: DriverBehaviorRead
    hos_history: list[DriverHoursRead] = []
    recent_trips: list[DriverTripRead] = []
