import uuid

from sqlalchemy import Boolean, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Hub(Base):
    """A physical depot/hub a vehicle dispatches from and returns to.

    Exists because `vehicle_master.base_location` is a free-text city name
    ("Hyderabad") with no coordinates, which the optimizer cannot route from -
    it needs a real lat/lon to build the hub->first-stop and last-stop->hub legs.
    Multiple vehicles can share one hub, so this is its own entity rather than
    columns duplicated onto every vehicle row.
    """

    __tablename__ = "hubs"

    hub_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    hub_type: Mapped[str] = mapped_column(String(20), default="DEPOT", nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
