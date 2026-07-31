import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DelayPredictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prediction_id: uuid.UUID
    trip_id: str
    delay_probability: float
    is_delayed_prediction: bool
    model_version: str
    features: dict[str, Any]
    predicted_at: datetime


class ExpectedDelayRead(BaseModel):
    predicted_delay_minutes: float
