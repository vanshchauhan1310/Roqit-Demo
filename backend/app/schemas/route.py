import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RouteStopBase(BaseModel):
    sequence: int
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    eta: datetime | None = None


class RouteStopCreate(RouteStopBase):
    pass


class RouteStopRead(RouteStopBase):
    model_config = ConfigDict(from_attributes=True)

    stop_id: uuid.UUID
    status: str


class RouteBase(BaseModel):
    trip_id: str | None = None
    name: str | None = None


class RouteCreate(RouteBase):
    stops: list[RouteStopCreate] = []


class RouteUpdateStatus(BaseModel):
    status: str


class RouteRead(RouteBase):
    model_config = ConfigDict(from_attributes=True)

    route_id: uuid.UUID
    status: str
    created_at: datetime
    stops: list[RouteStopRead] = []
