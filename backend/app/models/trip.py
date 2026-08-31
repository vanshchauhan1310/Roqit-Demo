from sqlalchemy import String, DateTime, Float, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Maps onto the real Supabase `trips` table (production data, not a scratch
# schema) - column names/types mirror it exactly. There is no stored
# is_delayed column: the real business rule is status == "Delayed"
# (delay_minutes > 90) - see ml/pipeline_documentation_v2.json.
DELAYED_STATUS = "Delayed"
RESOLVED_STATUSES = ("Delayed", "Delivered")


class Trip(Base):
    __tablename__ = "trips"

    trip_id: Mapped[str] = mapped_column(String, primary_key=True)
    driver_id: Mapped[str | None] = mapped_column(String, ForeignKey("driver_master.driver_id"))
    driver_name: Mapped[str | None] = mapped_column(String)
    vehicle_id: Mapped[str | None] = mapped_column(String, ForeignKey("vehicle_master.vehicle_id"))
    vehicle_type: Mapped[str | None] = mapped_column(String)
    origin: Mapped[str | None] = mapped_column(String)
    destination: Mapped[str | None] = mapped_column(String)

    gps_start_lat: Mapped[float | None] = mapped_column(Float)
    gps_start_lon: Mapped[float | None] = mapped_column(Float)
    gps_end_lat: Mapped[float | None] = mapped_column(Float)
    gps_end_lon: Mapped[float | None] = mapped_column(Float)
    planned_distance_km: Mapped[float | None] = mapped_column(Float)
    actual_distance_km: Mapped[float | None] = mapped_column(Float)

    pickup_time: Mapped[DateTime | None] = mapped_column(DateTime)
    planned_delivery_time: Mapped[DateTime | None] = mapped_column(DateTime)
    actual_delivery_time: Mapped[DateTime | None] = mapped_column(DateTime)
    delay_minutes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str | None] = mapped_column(String)

    weather_condition: Mapped[str | None] = mapped_column(String)
    road_type: Mapped[str | None] = mapped_column(String)
    traffic_density: Mapped[str | None] = mapped_column(String)

    odometer_start: Mapped[int | None] = mapped_column(BigInteger)
    odometer_end: Mapped[int | None] = mapped_column(BigInteger)
    fuel_consumed_l: Mapped[float | None] = mapped_column(Float)
    fuel_price_per_l: Mapped[float | None] = mapped_column(Float)
    fuel_cost: Mapped[float | None] = mapped_column(Float)
    driver_pay: Mapped[float | None] = mapped_column(Float)
    maintenance_cost: Mapped[float | None] = mapped_column(Float)
    toll_cost: Mapped[float | None] = mapped_column(Float)
    idle_time_min: Mapped[int | None] = mapped_column(BigInteger)
    load_weight_kg: Mapped[int | None] = mapped_column(BigInteger)
    load_value: Mapped[float | None] = mapped_column(Float)
    profit_margin: Mapped[float | None] = mapped_column(Float)
    violation_count: Mapped[int | None] = mapped_column(BigInteger)
    speeding_incidents: Mapped[int | None] = mapped_column(BigInteger)
    harsh_braking_count: Mapped[int | None] = mapped_column(BigInteger)
    harsh_accel_count: Mapped[int | None] = mapped_column(BigInteger)

    # Denormalized reference to the route this trip is assigned to (if any).
    # Set by the greedy insertion / new-route flow and cleared by LNS destroy.
    # Kept as a String (no FK) to avoid a UUID/string type mismatch while still
    # enabling the fast "is this trip already assigned?" checks.
    route_id: Mapped[str | None] = mapped_column(String, nullable=True)

    vehicle: Mapped["Vehicle"] = relationship(back_populates="trips")
    driver: Mapped["Driver"] = relationship(back_populates="trips")
    routes: Mapped[list["Route"]] = relationship()
    gps_breadcrumbs: Mapped[list["GpsBreadcrumb"]] = relationship(back_populates="trip")
    delay_predictions: Mapped[list["DelayPrediction"]] = relationship(back_populates="trip")

    @property
    def is_delayed(self) -> bool | None:
        """The real outcome label, per ml/pipeline_documentation_v2.json's target
        definition. None if the trip hasn't resolved yet (In-Transit/Cancelled)."""
        if self.status not in RESOLVED_STATUSES:
            return None
        return self.status == DELAYED_STATUS
