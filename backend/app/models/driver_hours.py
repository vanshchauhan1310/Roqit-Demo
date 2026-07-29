import uuid

from sqlalchemy import DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DriverHours(Base):
    __tablename__ = "driver_hours"

    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.driver_id"), nullable=False)
    shift_start: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_end: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    hours_driven: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    driver: Mapped["Driver"] = relationship(back_populates="driver_hours")
