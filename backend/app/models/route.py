import uuid

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Route(Base):
    __tablename__ = "routes"

    route_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[str | None] = mapped_column(String, ForeignKey("trips.trip_id"))
    name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="planned")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    driver_id: Mapped[str | None] = mapped_column(String, ForeignKey("driver_master.driver_id"))
    vehicle_id: Mapped[str | None] = mapped_column(String, ForeignKey("vehicle_master.vehicle_id"))
    pickup_time: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    planned_delivery_time: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    stops: Mapped[list["RouteStop"]] = relationship(back_populates="route", order_by="RouteStop.sequence")
    driver: Mapped["Driver"] = relationship()
    vehicle: Mapped["Vehicle"] = relationship()


class RouteStop(Base):
    __tablename__ = "route_stops"

    stop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("routes.route_id"), nullable=False)
    trip_id: Mapped[str | None] = mapped_column(String, ForeignKey("trips.trip_id"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    eta: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    stop_type: Mapped[str] = mapped_column(String(20), default="waypoint")
    window_start: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    weather_condition: Mapped[str | None] = mapped_column(String(50))
    weather_updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    route: Mapped["Route"] = relationship(back_populates="stops")
    trip: Mapped["Trip"] = relationship()
