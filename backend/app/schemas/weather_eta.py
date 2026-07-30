import uuid

from pydantic import BaseModel


class WeatherEtaEstimate(BaseModel):
    route_id: uuid.UUID

    origin_latitude: float
    origin_longitude: float

    weather_condition: str
    weather_description: str
    temperature_c: float | None
    wind_speed_ms: float | None

    distance_km: float
    base_duration_minutes: float
    weather_delay_multiplier: float
    adjusted_duration_minutes: float
