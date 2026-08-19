from datetime import datetime

from pydantic import BaseModel


class RealtimeLiveRead(BaseModel):
    trip_id: str
    status: str | None = None
    vehicle_id: str | None = None
    vehicle_status: str | None = None
    current_lat: float | None = None
    current_lon: float | None = None
    current_speed_kmph: float | None = None
    alert_flag: str | None = None
    last_updated: datetime | None = None
    breadcrumb_count: int = 0
    latest_speed_kmph: float | None = None
    latest_heading_deg: int | None = None
    latest_timestamp: datetime | None = None
