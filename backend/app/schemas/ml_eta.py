from datetime import datetime

from pydantic import BaseModel


class MlEtaEstimate(BaseModel):
    trip_id: str
    planned_duration_hours: float
    expected_delay_minutes: float
    predicted_delivery_time: datetime
