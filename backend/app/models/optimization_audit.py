"""Audit models for optimization tracking."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, func, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RouteAssignment(Base):
    """Audit log for every trip-to-route assignment."""
    __tablename__ = "route_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[str] = mapped_column(String, ForeignKey("trips.trip_id"), nullable=False)
    route_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("routes.route_id"), nullable=False)

    assignment_status: Mapped[str] = mapped_column(String(20), nullable=False)  # ASSIGNED, NEW_ROUTE, FAILED, UNASSIGNED
    insertion_position: Mapped[int | None] = mapped_column(Integer)

    # Cost breakdown
    additional_distance_km: Mapped[float | None] = mapped_column(Float)
    additional_duration_minutes: Mapped[float | None] = mapped_column(Float)
    delay_impact_minutes: Mapped[float | None] = mapped_column(Float)
    fuel_cost_rupees: Mapped[float | None] = mapped_column(Float)
    delay_risk: Mapped[float | None] = mapped_column(Float)
    change_penalty: Mapped[float | None] = mapped_column(Float)

    # Total score
    score: Mapped[float | None] = mapped_column(Float)

    # Reason/violations
    reason: Mapped[str | None] = mapped_column(Text)

    # Algorithm info
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)  # GREEDY_BEST_INSERTION, LNS_REPAIR, etc.
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)  # greedy-v1, lns-v1, etc.

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trip: Mapped["Trip"] = relationship()
    route: Mapped["Route"] = relationship()


class OptimizationRun(Base):
    """Audit log for optimization runs (both greedy and LNS)."""
    __tablename__ = "optimization_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    optimization_type: Mapped[str] = mapped_column(String(20), nullable=False)  # ONLINE_GREEDY, PERIODIC_LNS, TRIGGERED_LNS

    # For greedy: the trip that triggered it
    trip_id: Mapped[str | None] = mapped_column(String, ForeignKey("trips.trip_id"))

    # Candidate stats
    candidate_routes_count: Mapped[int] = mapped_column(Integer, default=0)
    feasible_routes_count: Mapped[int] = mapped_column(Integer, default=0)

    # Affected routes
    routes_affected: Mapped[int] = mapped_column(Integer, default=0)

    # Cost comparison
    old_cost: Mapped[float | None] = mapped_column(Float)
    new_cost: Mapped[float | None] = mapped_column(Float)
    improvement: Mapped[float | None] = mapped_column(Float)

    # Execution info
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)

    # LNS run details
    trips_reinserted: Mapped[int | None] = mapped_column(Integer)
    destroy_strategy: Mapped[str | None] = mapped_column(String(30))
    repair_strategy: Mapped[str | None] = mapped_column(String(30))

    # Full plan snapshots for before/after comparison (LNS only).
    # Shape: {route_id: {name, vehicle_id, stops: [{stop_id, trip_id, sequence,
    #         stop_type, address, latitude, longitude}]}}
    routes_before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    routes_after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Algorithm info
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(20), default="completed")  # completed, failed, rolled_back

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trip: Mapped["Trip"] = relationship()