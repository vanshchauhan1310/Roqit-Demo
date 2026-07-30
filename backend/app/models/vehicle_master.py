from sqlalchemy import BigInteger, Column, Float, String

from app.db.base import Base


class VehicleMaster(Base):
    """Real, CSV-imported vehicle roster. Read-only from the app's perspective."""

    __tablename__ = "vehicle_master"

    vehicle_id = Column(String, primary_key=True)
    vehicle_type = Column(String, nullable=True)
    make = Column(String, nullable=True)
    model = Column(String, nullable=True)
    year = Column(BigInteger, nullable=True)
    purchase_date = Column(String, nullable=True)
    fuel_type = Column(String, nullable=True)
    tank_capacity_l = Column(BigInteger, nullable=True)
    load_capacity_kg = Column(BigInteger, nullable=True)
    odometer_km = Column(BigInteger, nullable=True)
    avg_kmpl_rated = Column(Float, nullable=True)
    base_location = Column(String, nullable=True)
    last_service_date = Column(String, nullable=True)
    next_service_due_km = Column(BigInteger, nullable=True)
    insurance_expiry = Column(String, nullable=True)
    registration_expiry = Column(String, nullable=True)
    gps_device_id = Column(String, nullable=True)
    status = Column(String, nullable=True)
