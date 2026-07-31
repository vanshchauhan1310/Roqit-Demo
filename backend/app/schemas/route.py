import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.weather_eta import WeatherEtaEstimate


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
    computed_status: str | None = None

    weather_condition: str | None = None
    weather_description: str | None = None
    temperature_c: float | None = None
    wind_speed_ms: float | None = None


class RouteBase(BaseModel):
    trip_id: str | None = None
    name: str | None = None


class RouteCreate(RouteBase):
    stops: list[RouteStopCreate] = []


class RouteUpdateStatus(BaseModel):
    status: str


class RouteAssignTrip(BaseModel):
    trip_id: str


class RouteRead(RouteBase):
    model_config = ConfigDict(from_attributes=True)

    route_id: uuid.UUID
    status: str
    created_at: datetime
    stops: list[RouteStopRead] = []
    weather_eta: WeatherEtaEstimate | None = None
