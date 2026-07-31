from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GpsBreadcrumbRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    lat: float | None
    lon: float | None
    speed_kmph: float | None
    heading_deg: int | None
