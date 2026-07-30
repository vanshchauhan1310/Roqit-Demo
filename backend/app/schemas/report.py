from pydantic import BaseModel


class TripKpiSummary(BaseModel):
    total_trips: int
    on_time_rate: float | None = None
    avg_delay_minutes: float | None = None
    avg_profit_margin: float | None = None
    active_trips: int
    delayed_trips: int
