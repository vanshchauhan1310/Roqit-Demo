import uuid
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict


class RouteStopBase(BaseModel):
    sequence: int | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    eta: datetime | None = None
    stop_type: str = "waypoint"
    window_start: datetime | None = None
    window_end: datetime | None = None


class RouteStopCreate(RouteStopBase):
    pass


class RouteStopRead(RouteStopBase):
    model_config = ConfigDict(from_attributes=True)

    stop_id: uuid.UUID
    status: str
    weather_condition: str | None = None
    weather_updated_at: datetime | None = None
    trip_id: str | None = None


class RouteBase(BaseModel):
    trip_id: str | None = None
    name: str | None = None


class RouteCreate(RouteBase):
    stops: list[RouteStopCreate] = []


class RouteUpdateStatus(BaseModel):
    status: str


class RouteAssignTrip(BaseModel):
    trip_id: str


class TripLoadInput(BaseModel):
    trip_id: str
    load_weight_kg: int | None = None
    load_value: float | None = None


class RouteAssignRequest(BaseModel):
    trip_ids: List[str]
    driver_id: str
    vehicle_id: str
    pickup_time: datetime
    name: str | None = None
    loads: List[TripLoadInput] = []


class RouteReorderRequest(BaseModel):
    stop_ids: List[uuid.UUID]


class RouteRead(RouteBase):
    model_config = ConfigDict(from_attributes=True)

    route_id: uuid.UUID
    status: str
    created_at: datetime
    stops: list[RouteStopRead] = []
    driver_id: str | None = None
    vehicle_id: str | None = None
    pickup_time: datetime | None = None
    planned_delivery_time: datetime | None = None
    weather_eta: datetime | None = None  # rule-based (OSRM + weather multiplier), not ML — see eta_service.py
