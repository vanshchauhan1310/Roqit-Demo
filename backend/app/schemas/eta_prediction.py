from datetime import datetime

from pydantic import BaseModel


class EtaPredictionRead(BaseModel):
    """Rule-based (not ML) weather-adjusted ETA — see eta_service.py."""

    weather_condition: str | None = None
    weather_multiplier: float | None = None
    predicted_delivery_time: datetime | None = None
    expected_delay_minutes: float | None = None
