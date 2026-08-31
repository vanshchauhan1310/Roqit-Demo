"""add hubs, vehicle/driver dispatch cost config, and fuel prices

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-08-20 12:00:00.000000

Additive-only: CREATEs four new tables and touches nothing that already holds
data. Following the boundary a1b2c3d4e5f6 set out, the CSV-imported master
tables (vehicle_master, driver_master) are NOT altered - vehicle hub assignment
and cost rates live in side tables keyed by the master row's id instead, so a
CSV re-import can never clobber optimizer configuration.

Every rate column is nullable by design: a missing rate must remain
distinguishable from a rate of zero so the fleet optimizer can return
MISSING_COST_DATA rather than costing something at 0.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hubs",
        sa.Column("hub_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("hub_type", sa.String(length=20), server_default="DEPOT", nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("hub_id"),
    )

    op.create_table(
        "vehicle_dispatch_config",
        sa.Column("vehicle_id", sa.String(), nullable=False),
        sa.Column("base_hub_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("end_hub_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fixed_route_cost", sa.Float(), nullable=True),
        sa.Column("cost_per_km", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicle_master.vehicle_id"]),
        sa.ForeignKeyConstraint(["base_hub_id"], ["hubs.hub_id"]),
        sa.ForeignKeyConstraint(["end_hub_id"], ["hubs.hub_id"]),
        sa.PrimaryKeyConstraint("vehicle_id"),
    )

    op.create_table(
        "driver_dispatch_config",
        sa.Column("driver_id", sa.String(), nullable=False),
        sa.Column("cost_per_hour", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["driver_master.driver_id"]),
        sa.PrimaryKeyConstraint("driver_id"),
    )

    op.create_table(
        "fuel_prices",
        sa.Column("fuel_price_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fuel_type", sa.String(length=20), nullable=False),
        sa.Column("price_per_liter", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("fuel_price_id"),
    )
    # Current-price lookup is "latest effective_from for this fuel_type", run on
    # every fleet optimize request.
    op.create_index("ix_fuel_prices_type_effective", "fuel_prices", ["fuel_type", "effective_from"])


def downgrade() -> None:
    op.drop_index("ix_fuel_prices_type_effective", table_name="fuel_prices")
    op.drop_table("fuel_prices")
    op.drop_table("driver_dispatch_config")
    op.drop_table("vehicle_dispatch_config")
    op.drop_table("hubs")
