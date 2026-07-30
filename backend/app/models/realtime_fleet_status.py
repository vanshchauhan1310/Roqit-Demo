from sqlalchemy import Column, DateTime, Float, String

from app.db.base import Base


class RealtimeFleetStatus(Base):
    """Real, CSV-imported live vehicle status snapshot. Read-only from the app's perspective."""

    __tablename__ = "realtime_fleet_status"

    vehicle_id = Column(String, primary_key=True)
    current_trip_id = Column(String, nullable=True)
    current_lat = Column(Float, nullable=True)
    current_lon = Column(Float, nullable=True)
    current_speed_kmph = Column(Float, nullable=True)
    status = Column(String, nullable=True)
    alert_flag = Column(String, nullable=True)
    last_updated = Column(DateTime(timezone=True), nullable=True)
