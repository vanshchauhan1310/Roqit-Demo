"""create routes, route_stops, and other new tables (drivers/vehicles/gps_breadcrumbs/maintenance_events)

Revision ID: a1b2c3d4e5f6
Revises: 000000000000
Create Date: 2026-07-29 16:00:00.000000

Note: this intentionally only CREATEs new, empty tables that don't exist yet.
It does not touch trips, driver_hours, or any of the pre-existing CSV-imported
tables (driver_master, vehicle_master, gps_breadcrumb, maintance_event,
realtime_fleet_status) — those already hold real data and are out of scope.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "000000000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drivers",
        sa.Column("driver_id", sa.UUID(), nullable=False),
        sa.Column("first_name", sa.String(length=50), nullable=False),
        sa.Column("last_name", sa.String(length=50), nullable=False),
        sa.Column("license_number", sa.String(length=50), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("driver_id"),
        sa.UniqueConstraint("license_number"),
    )
    op.create_table(
        "vehicles",
        sa.Column("vehicle_id", sa.UUID(), nullable=False),
        sa.Column("license_plate", sa.String(length=20), nullable=False),
        sa.Column("make", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("vehicle_id"),
        sa.UniqueConstraint("license_plate"),
    )
    op.create_table(
        "gps_breadcrumbs",
        sa.Column("breadcrumb_id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.String(), nullable=False),
        sa.Column("vehicle_id", sa.UUID(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.trip_id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.vehicle_id"]),
        sa.PrimaryKeyConstraint("breadcrumb_id"),
    )
    op.create_table(
        "maintenance_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("vehicle_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.vehicle_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_table(
        "routes",
        sa.Column("route_id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.trip_id"]),
        sa.PrimaryKeyConstraint("route_id"),
    )
    op.create_table(
        "route_stops",
        sa.Column("stop_id", sa.UUID(), nullable=False),
        sa.Column("route_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stop_type", sa.String(length=20), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["route_id"], ["routes.route_id"]),
        sa.PrimaryKeyConstraint("stop_id"),
    )


def downgrade() -> None:
    op.drop_table("route_stops")
    op.drop_table("routes")
    op.drop_table("maintenance_events")
    op.drop_table("gps_breadcrumbs")
    op.drop_table("vehicles")
    op.drop_table("drivers")
