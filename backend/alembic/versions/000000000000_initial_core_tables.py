"""reconstruct lost initial schema (core CSV-imported tables).

Revision ID: 000000000000
Revises: None
Create Date: 2026-09-04

The original base migration (and old-chain root 3bd8ab2c9348) were never
committed to this repo, which left 1755ff316ef3 / a1b2c3d4e5f6 pointing at a
non-existent revision 000000000000 and broke `alembic upgrade head` at startup.

This migration recreates the core, CSV-imported tables that every later
migration depends on (trips is referenced by delay_predictions, gps_breadcrumbs,
routes and route_stops; driver_master / vehicle_master by the routes FKs).
Column definitions match the live production schema exactly. Each create is
guarded so it is a no-op on databases that already have these tables (e.g. the
existing volume stamped at 7a8b9c0d1e2f, which is now a descendant of this
revision via the merge b43192b98712).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "000000000000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_if_missing(table_name: str, *columns) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(table_name):
        return
    op.create_table(table_name, *columns)


def upgrade() -> None:
    _create_if_missing(
        "trips",
        sa.Column("trip_id", sa.String(), nullable=False),
        sa.Column("driver_id", sa.String(), nullable=True),
        sa.Column("driver_name", sa.String(), nullable=True),
        sa.Column("vehicle_id", sa.String(), nullable=True),
        sa.Column("vehicle_type", sa.String(), nullable=True),
        sa.Column("origin", sa.String(), nullable=True),
        sa.Column("destination", sa.String(), nullable=True),
        sa.Column("gps_start_lat", sa.Float(), nullable=True),
        sa.Column("gps_start_lon", sa.Float(), nullable=True),
        sa.Column("gps_end_lat", sa.Float(), nullable=True),
        sa.Column("gps_end_lon", sa.Float(), nullable=True),
        sa.Column("planned_distance_km", sa.Float(), nullable=True),
        sa.Column("actual_distance_km", sa.Float(), nullable=True),
        sa.Column("pickup_time", sa.DateTime(), nullable=True),
        sa.Column("planned_delivery_time", sa.DateTime(), nullable=True),
        sa.Column("actual_delivery_time", sa.DateTime(), nullable=True),
        sa.Column("delay_minutes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("weather_condition", sa.String(), nullable=True),
        sa.Column("road_type", sa.String(), nullable=True),
        sa.Column("traffic_density", sa.String(), nullable=True),
        sa.Column("odometer_start", sa.BigInteger(), nullable=True),
        sa.Column("odometer_end", sa.BigInteger(), nullable=True),
        sa.Column("fuel_consumed_l", sa.Float(), nullable=True),
        sa.Column("fuel_price_per_l", sa.Float(), nullable=True),
        sa.Column("fuel_cost", sa.Float(), nullable=True),
        sa.Column("driver_pay", sa.Float(), nullable=True),
        sa.Column("maintenance_cost", sa.Float(), nullable=True),
        sa.Column("toll_cost", sa.Float(), nullable=True),
        sa.Column("idle_time_min", sa.BigInteger(), nullable=True),
        sa.Column("load_weight_kg", sa.BigInteger(), nullable=True),
        sa.Column("load_value", sa.Float(), nullable=True),
        sa.Column("profit_margin", sa.Float(), nullable=True),
        sa.Column("violation_count", sa.BigInteger(), nullable=True),
        sa.Column("speeding_incidents", sa.BigInteger(), nullable=True),
        sa.Column("harsh_braking_count", sa.BigInteger(), nullable=True),
        sa.Column("harsh_accel_count", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("trip_id"),
    )
    _create_if_missing(
        "driver_master",
        sa.Column("driver_id", sa.String(), nullable=False),
        sa.Column("driver_name", sa.String(), nullable=True),
        sa.Column("phone", sa.BigInteger(), nullable=True),
        sa.Column("license_type", sa.String(), nullable=True),
        sa.Column("license_expiry", sa.String(), nullable=True),
        sa.Column("date_joined", sa.String(), nullable=True),
        sa.Column("experience_years", sa.Float(), nullable=True),
        sa.Column("base_location", sa.String(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("driver_id"),
    )
    _create_if_missing(
        "vehicle_master",
        sa.Column("vehicle_id", sa.String(), nullable=False),
        sa.Column("vehicle_type", sa.String(), nullable=True),
        sa.Column("make", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("year", sa.BigInteger(), nullable=True),
        sa.Column("purchase_date", sa.String(), nullable=True),
        sa.Column("fuel_type", sa.String(), nullable=True),
        sa.Column("tank_capacity_l", sa.BigInteger(), nullable=True),
        sa.Column("load_capacity_kg", sa.BigInteger(), nullable=True),
        sa.Column("odometer_km", sa.BigInteger(), nullable=True),
        sa.Column("avg_kmpl_rated", sa.Float(), nullable=True),
        sa.Column("base_location", sa.String(), nullable=True),
        sa.Column("last_service_date", sa.String(), nullable=True),
        sa.Column("next_service_due_km", sa.BigInteger(), nullable=True),
        sa.Column("insurance_expiry", sa.String(), nullable=True),
        sa.Column("registration_expiry", sa.String(), nullable=True),
        sa.Column("gps_device_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("vehicle_id"),
    )
    _create_if_missing(
        "driver_hours",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("driver_id", sa.String(), nullable=True),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("trips_count", sa.BigInteger(), nullable=True),
        sa.Column("hours_driven", sa.Float(), nullable=True),
        sa.Column("rest_hours", sa.Float(), nullable=True),
        sa.Column("hos_compliant", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_if_missing(
        "fuel_prices",
        sa.Column("fuel_price_id", sa.UUID(), nullable=False),
        sa.Column("fuel_type", sa.String(length=20), nullable=False),
        sa.Column("price_per_liter", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("fuel_price_id"),
    )
    _create_if_missing(
        "gps_breadcrumb",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("trip_id", sa.String(), nullable=False),
        sa.Column("vehicle_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("speed_kmph", sa.Float(), nullable=True),
        sa.Column("heading_deg", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_if_missing(
        "maintance_event",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("vehicle_id", sa.String(), nullable=True),
        sa.Column("event_date", sa.String(), nullable=True),
        sa.Column("maintenance_type", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("downtime_hours", sa.Float(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("odometer_at_service", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    _create_if_missing(
        "realtime_fleet_status",
        sa.Column("vehicle_id", sa.String(), nullable=False),
        sa.Column("current_trip_id", sa.String(), nullable=True),
        sa.Column("current_lat", sa.Float(), nullable=True),
        sa.Column("current_lon", sa.Float(), nullable=True),
        sa.Column("current_speed_kmph", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("alert_flag", sa.String(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("vehicle_id"),
    )
    _create_if_missing(
        "driver_dispatch_config",
        sa.Column("driver_id", sa.String(), nullable=False),
        sa.Column("cost_per_hour", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("driver_id"),
    )
    _create_if_missing(
        "vehicle_dispatch_config",
        sa.Column("vehicle_id", sa.String(), nullable=False),
        sa.Column("base_hub_id", sa.UUID(), nullable=True),
        sa.Column("end_hub_id", sa.UUID(), nullable=True),
        sa.Column("fixed_route_cost", sa.Float(), nullable=True),
        sa.Column("cost_per_km", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("vehicle_id"),
    )
    _create_if_missing(
        "hubs",
        sa.Column("hub_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("hub_type", sa.String(length=20), server_default="DEPOT", nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("hub_id"),
    )


def downgrade() -> None:
    # The lost base migration has no recorded downgrade; tables are dropped in
    # reverse dependency order only if they exist.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in (
        "hubs",
        "vehicle_dispatch_config",
        "driver_dispatch_config",
        "realtime_fleet_status",
        "maintance_event",
        "gps_breadcrumb",
        "fuel_prices",
        "driver_hours",
        "vehicle_master",
        "driver_master",
        "trips",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)
