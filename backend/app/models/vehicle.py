from datetime import date

from sqlalchemy import String, Float, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Maps onto the real Supabase `vehicle_master` table.
class Vehicle(Base):
    __tablename__ = "vehicle_master"

    vehicle_id: Mapped[str] = mapped_column(String, primary_key=True)
    vehicle_type: Mapped[str | None] = mapped_column(String)
    make: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(BigInteger)
    purchase_date: Mapped[str | None] = mapped_column(String)
    fuel_type: Mapped[str | None] = mapped_column(String)
    tank_capacity_l: Mapped[int | None] = mapped_column(BigInteger)
    load_capacity_kg: Mapped[int | None] = mapped_column(BigInteger)
    odometer_km: Mapped[int | None] = mapped_column(BigInteger)
    avg_kmpl_rated: Mapped[float | None] = mapped_column(Float)
    base_location: Mapped[str | None] = mapped_column(String)
    last_service_date: Mapped[str | None] = mapped_column(String)
    next_service_due_km: Mapped[int | None] = mapped_column(BigInteger)
    insurance_expiry: Mapped[str | None] = mapped_column(String)
    registration_expiry: Mapped[str | None] = mapped_column(String)
    gps_device_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)

    trips: Mapped[list["Trip"]] = relationship(back_populates="vehicle")

    @property
    def vehicle_age_years(self) -> float | None:
        """Not a stored column - the training data derives it as
        current_year - year (verified empirically against train_v2.csv)."""
        if self.year is None:
            return None
        return float(date.today().year - self.year)
