from sqlalchemy import BigInteger, Column, Float, String

from app.db.base import Base


class DriverMaster(Base):
    """Real, CSV-imported driver roster. Read-only from the app's perspective."""

    __tablename__ = "driver_master"

    driver_id = Column(String, primary_key=True)
    driver_name = Column(String, nullable=True)
    phone = Column(BigInteger, nullable=True)
    license_type = Column(String, nullable=True)
    license_expiry = Column(String, nullable=True)
    date_joined = Column(String, nullable=True)
    experience_years = Column(Float, nullable=True)
    base_location = Column(String, nullable=True)
    rating = Column(Float, nullable=True)
    status = Column(String, nullable=True)
