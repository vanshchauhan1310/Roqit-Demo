from sqlalchemy import BigInteger, Column, DateTime, Float, String

from app.db.base import Base


class Trip(Base):
    __tablename__ = "trips"

    trip_id = Column(String, primary_key=True)
    driver_id = Column(String, nullable=True)
    driver_name = Column(String, nullable=True)
    vehicle_id = Column(String, nullable=True)
    vehicle_type = Column(String, nullable=True)

    origin = Column(String, nullable=True)
    destination = Column(String, nullable=True)

    gps_start_lat = Column(Float, nullable=True)
    gps_start_lon = Column(Float, nullable=True)
    gps_end_lat = Column(Float, nullable=True)
    gps_end_lon = Column(Float, nullable=True)

    planned_distance_km = Column(Float, nullable=True)
    actual_distance_km = Column(Float, nullable=True)

    pickup_time = Column(DateTime(timezone=True), nullable=True)
    planned_delivery_time = Column(DateTime(timezone=True), nullable=True)
    actual_delivery_time = Column(DateTime(timezone=True), nullable=True)

    delay_minutes = Column(BigInteger, nullable=True)
    status = Column(String, nullable=True)

    weather_condition = Column(String, nullable=True)
    road_type = Column(String, nullable=True)
    traffic_density = Column(String, nullable=True)

    odometer_start = Column(BigInteger, nullable=True)
    odometer_end = Column(BigInteger, nullable=True)

    fuel_consumed_l = Column(Float, nullable=True)
    fuel_price_per_l = Column(Float, nullable=True)
    fuel_cost = Column(Float, nullable=True)
    driver_pay = Column(Float, nullable=True)
    maintenance_cost = Column(Float, nullable=True)
    toll_cost = Column(Float, nullable=True)

    idle_time_min = Column(BigInteger, nullable=True)
    load_weight_kg = Column(BigInteger, nullable=True)
    load_value = Column(Float, nullable=True)
    profit_margin = Column(Float, nullable=True)

    violation_count = Column(BigInteger, nullable=True)
    speeding_incidents = Column(BigInteger, nullable=True)
    harsh_braking_count = Column(BigInteger, nullable=True)
    harsh_accel_count = Column(BigInteger, nullable=True)
