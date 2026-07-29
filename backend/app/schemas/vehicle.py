import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VehicleBase(BaseModel):
    license_plate: str
    make: str | None = None
    model: str | None = None
    year: int | None = None


class VehicleCreate(VehicleBase):
    pass


class VehicleRead(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: uuid.UUID
    status: str
    created_at: datetime
