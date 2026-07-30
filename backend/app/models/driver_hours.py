from sqlalchemy import String, Boolean, Float, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Maps onto the real Supabase `driver_hours` table: a daily fleet-wide
# aggregate (no vehicle_id/trip_id grain - see ml training notebook Phase 1).
# No FK constraint exists on driver_id at the DB level either.
class DriverHours(Base):
    __tablename__ = "driver_hours"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    driver_id: Mapped[str | None] = mapped_column(String)
    date: Mapped[str | None] = mapped_column(String)
    trips_count: Mapped[int | None] = mapped_column(BigInteger)
    hours_driven: Mapped[float | None] = mapped_column(Float)
    rest_hours: Mapped[float | None] = mapped_column(Float)
    hos_compliant: Mapped[bool | None] = mapped_column(Boolean)
