from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GpsBreadcrumbRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trip_id: str
    vehicle_id: str | None = None
    timestamp: datetime
    lat: float | None = None
    lon: float | None = None
    speed_kmph: float | None = None
    heading_deg: int | None = None
