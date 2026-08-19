from pydantic import BaseModel


class TripKpiSummary(BaseModel):
    total_trips: int
    on_time_rate: float | None = None
    avg_delay_minutes: float | None = None
    avg_profit_margin: float | None = None
    active_trips: int
    delayed_trips: int


class StatusBucket(BaseModel):
    status: str
    count: int


class DelayBucket(BaseModel):
    label: str  # e.g. "On time", "≤30m", "31–60m", "61–90m", ">90m"
    count: int


class TripKpiDetail(TripKpiSummary):
    status_distribution: list[StatusBucket] = []
    delay_buckets: list[DelayBucket] = []
