from pydantic import BaseModel, ConfigDict


class DriverBase(BaseModel):
    driver_name: str
    phone: int | None = None
    license_type: str | None = None
    experience_years: float | None = None
    rating: float | None = None
    base_location: str | None = None


class DriverCreate(DriverBase):
    driver_id: str
    status: str | None = "active"


class DriverRead(DriverBase):
    model_config = ConfigDict(from_attributes=True)

    driver_id: str
    status: str | None = None
