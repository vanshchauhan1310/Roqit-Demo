from sqlalchemy import String, Float, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Maps onto the real Supabase `maintance_event` table (typo preserved -
# that's the actual table name in production).
class MaintenanceEvent(Base):
    __tablename__ = "maintance_event"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    vehicle_id: Mapped[str | None] = mapped_column(String, ForeignKey("vehicle_master.vehicle_id"))
    event_date: Mapped[str | None] = mapped_column(String)
    maintenance_type: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    downtime_hours: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    odometer_at_service: Mapped[int | None] = mapped_column(BigInteger)

    vehicle: Mapped["Vehicle"] = relationship()
