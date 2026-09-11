import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Forecast(Base):
    __tablename__ = "forecasts"

    trip_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    weather_condition: Mapped[str | None] = mapped_column(String(50))
    weather_temp_c: Mapped[float | None] = mapped_column(Float)
    weather_humidity: Mapped[float | None] = mapped_column(Float)
    weather_wind_speed: Mapped[float | None] = mapped_column(Float)
    weather_description: Mapped[str | None] = mapped_column(String(200))
    traffic_density: Mapped[str | None] = mapped_column(String(20))
    road_type: Mapped[str | None] = mapped_column(String(30))
    eta_minutes: Mapped[float | None] = mapped_column(Float)
    predicted_delivery_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_delay_minutes: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=timezone.utc)
    )
