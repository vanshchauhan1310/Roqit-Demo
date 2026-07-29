import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DriverBase(BaseModel):
    first_name: str
    last_name: str
    license_number: str
    phone: str | None = None


class DriverCreate(DriverBase):
    pass


class DriverRead(DriverBase):
    model_config = ConfigDict(from_attributes=True)

    driver_id: uuid.UUID
    status: str
    created_at: datetime
