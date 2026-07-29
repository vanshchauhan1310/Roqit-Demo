import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TripBase(BaseModel):
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    origin: str | None = None
    destination: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


class TripCreate(TripBase):
    pass


class TripUpdateStatus(BaseModel):
    status: str


class TripRead(TripBase):
    model_config = ConfigDict(from_attributes=True)

    trip_id: uuid.UUID
    status: str
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    created_at: datetime
    updated_at: datetime
