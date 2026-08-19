from datetime import datetime

from pydantic import BaseModel


class EtaPredictionRead(BaseModel):
    """ETA from the ML model when trained, else the rule-based weather-adjusted
    estimate — see eta_service.py."""

    weather_condition: str | None = None
    weather_multiplier: float | None = None
    predicted_delivery_time: datetime | None = None
    expected_delay_minutes: float | None = None
