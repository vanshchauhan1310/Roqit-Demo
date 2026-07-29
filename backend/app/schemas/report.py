from pydantic import BaseModel


class TripKpiSummary(BaseModel):
    total_trips: int
    completed_trips: int
    in_progress_trips: int
    cancelled_trips: int
    on_time_rate: float | None = None
