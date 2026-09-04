"""Dispatch/costing configuration that the optimizer needs but the CSV-imported
master tables don't carry.

WHY THESE ARE SIDE TABLES, NOT COLUMNS ON vehicle_master / driver_master
-----------------------------------------------------------------------
Migration a1b2c3d4e5f6 states the rule explicitly: alembic here "does not touch
trips, driver_hours, or any of the pre-existing CSV-imported tables
(driver_master, vehicle_master, ...) - those already hold real data and are out
of scope." Adding cost/hub columns to those tables would break that boundary and
put optimizer configuration inside rows a CSV re-import may overwrite.

Keying config to the master row by id instead is additive, leaves the imported
data untouched, and mirrors how `routes` already FKs to
vehicle_master.vehicle_id / driver_master.driver_id.

Every rate is nullable on purpose: a missing rate must stay distinguishable from
a rate of zero, so the fleet optimizer can report MISSING_COST_DATA rather than
silently costing something at 0 (the same unknown-vs-zero rule already applied
to trip weight).
"""

import uuid

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VehicleDispatchConfig(Base):
    __tablename__ = "vehicle_dispatch_config"

    vehicle_id: Mapped[str] = mapped_column(
        String, ForeignKey("vehicle_master.vehicle_id"), primary_key=True
    )
    # Where this vehicle starts. end_hub_id is NULL for the common
    # "returns to the hub it left from" case - resolved at read time.
    base_hub_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hubs.hub_id"))
    end_hub_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hubs.hub_id"))
    # Cost of putting this vehicle on the road at all, independent of distance.
    # This is what makes the optimizer justify each extra vehicle it activates.
    fixed_route_cost: Mapped[float | None] = mapped_column(Float)
    # Operating cost per km EXCLUDING fuel (tyres, wear, maintenance accrual) -
    # fuel is costed separately from litres x fuel price so it stays load-aware.
    cost_per_km: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DriverDispatchConfig(Base):
    """Driver cost rate only. Deliberately has no home_hub/start_location: the
    current dispatch workflow starts every route from the assigned VEHICLE's hub,
    so a driver location field would be unused - added only if the business rules
    later require drivers to originate somewhere other than the vehicle."""

    __tablename__ = "driver_dispatch_config"

    driver_id: Mapped[str] = mapped_column(
        String, ForeignKey("driver_master.driver_id"), primary_key=True
    )
    # Fully-loaded hourly cost of this driver's time for route costing. NOT the
    # same as payroll salary - populate it with whatever the business defines as
    # the marginal cost of an hour on the road.
    cost_per_hour: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FuelPrice(Base):
    """Effective-dated fuel price per fuel type.

    fuel_type values mirror the two the app actually uses (vehicle_master.fuel_type
    and the ML feature contract's Literal["CNG", "Diesel"]). Petrol/EV rows are
    not modelled because no such vehicles exist here.
    """

    __tablename__ = "fuel_prices"

    fuel_price_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fuel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    price_per_liter: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    effective_from: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL = still in effect. The current price for a fuel type is the row with
    # the latest effective_from whose effective_to is NULL or in the future.
    effective_to: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    region: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
