from pydantic import BaseModel
from datetime import datetime


class DriverRosterItem(BaseModel):
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
    # New assignment-aware fields
    assignment_status: str = "available"  # "available" | "assigned" | "unavailable"
    current_route_id: str | None = None
    current_route_name: str | None = None
    current_route_pickup_time: datetime | None = None
    current_route_planned_delivery_time: datetime | None = None


class VehicleRosterItem(BaseModel):
    vehicle_id: str
    vehicle_type: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    fuel_type: str | None = None
    load_capacity_kg: int | None = None
    avg_kmpl_rated: float | None = None
    base_location: str | None = None
    hub_name: str | None = None
    status: str | None = None
    is_on_trip: bool
    service_due_soon: bool | None = None
    # New assignment-aware fields
    assignment_status: str = "available"  # "available" | "assigned" | "unavailable"
    current_route_id: str | None = None
    current_route_name: str | None = None
    current_route_pickup_time: datetime | None = None
    current_route_planned_delivery_time: datetime | None = None
