from sqlalchemy import String, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Maps onto the real Supabase `realtime_fleet_status` table - one row per
# vehicle, updated as new GPS data arrives. This is the actual "New GPS Data"
# entry point: current_trip_id + last_updated tell us which trip most
# recently received live telemetry.
class RealtimeFleetStatus(Base):
    __tablename__ = "realtime_fleet_status"

    vehicle_id: Mapped[str] = mapped_column(String, ForeignKey("vehicle_master.vehicle_id"), primary_key=True)
    current_trip_id: Mapped[str | None] = mapped_column(String, ForeignKey("trips.trip_id"))
    current_lat: Mapped[float | None] = mapped_column(Float)
    current_lon: Mapped[float | None] = mapped_column(Float)
    current_speed_kmph: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String)
    alert_flag: Mapped[str | None] = mapped_column(String)
    last_updated: Mapped[DateTime | None] = mapped_column(DateTime)

    vehicle: Mapped["Vehicle"] = relationship()
