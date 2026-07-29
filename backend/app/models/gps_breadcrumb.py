from sqlalchemy import String, DateTime, Float, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Maps onto the real Supabase `gps_breadcrumb` table (singular - not our
# earlier scaffold's `gps_breadcrumbs`).
class GpsBreadcrumb(Base):
    __tablename__ = "gps_breadcrumb"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trip_id: Mapped[str] = mapped_column(String, ForeignKey("trips.trip_id"), nullable=False)
    vehicle_id: Mapped[str | None] = mapped_column(String, ForeignKey("vehicle_master.vehicle_id"))
    timestamp: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    speed_kmph: Mapped[float | None] = mapped_column(Float)
    heading_deg: Mapped[int | None] = mapped_column(BigInteger)

    trip: Mapped["Trip"] = relationship(back_populates="gps_breadcrumbs")
