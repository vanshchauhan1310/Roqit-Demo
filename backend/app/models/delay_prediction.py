import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DelayPrediction(Base):
    __tablename__ = "delay_predictions"

    prediction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[str] = mapped_column(String, ForeignKey("trips.trip_id"), nullable=False)
    delay_probability: Mapped[float] = mapped_column(Float, nullable=False)
    is_delayed_prediction: Mapped[bool] = mapped_column(Boolean, nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    predicted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trip: Mapped["Trip"] = relationship(back_populates="delay_predictions")
