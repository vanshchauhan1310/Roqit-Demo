from pydantic import BaseModel, ConfigDict


class VehicleBase(BaseModel):
    vehicle_type: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    fuel_type: str | None = None
    load_capacity_kg: int | None = None


class VehicleCreate(VehicleBase):
    vehicle_id: str


class VehicleRead(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: str
    status: str | None = None
    vehicle_age_years: float | None = None
