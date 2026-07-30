from sqlalchemy import String, Float, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Maps onto the real Supabase `driver_master` table.
class Driver(Base):
    __tablename__ = "driver_master"

    driver_id: Mapped[str] = mapped_column(String, primary_key=True)
    driver_name: Mapped[str | None] = mapped_column(String)
    phone: Mapped[int | None] = mapped_column(BigInteger)
    license_type: Mapped[str | None] = mapped_column(String)
    license_expiry: Mapped[str | None] = mapped_column(String)
    date_joined: Mapped[str | None] = mapped_column(String)
    experience_years: Mapped[float | None] = mapped_column(Float)
    base_location: Mapped[str | None] = mapped_column(String)
    rating: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String)

    trips: Mapped[list["Trip"]] = relationship(back_populates="driver")
