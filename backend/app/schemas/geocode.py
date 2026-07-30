from pydantic import BaseModel


class GeocodeRequest(BaseModel):
    address: str


class GeocodeResult(BaseModel):
    lat: float
    lng: float
    error_radius: float | None = None
