"""add missing route assignment columns (driver_id, vehicle_id, pickup_time, planned_delivery_time)

Revision ID: 4f1a2b3c4d5e
Revises: 0001_baseline
Create Date: 2026-09-02

The Route ORM model (backend/app/models/route.py) declares driver_id, vehicle_id,
pickup_time, and planned_delivery_time.

On a fresh docker DB the routes table comes from 0001_baseline which creates all tables
from SQLAlchemy models. This migration adds the columns if they don't already exist
(idempotent) and is a no-op on databases that already have these columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f1a2b3c4d5e"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table_name)]
    return column_name in columns


def _constraint_exists(constraint_name: str, table_name: str) -> bool:
    """Check if a constraint exists on a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = [c["name"] for c in inspector.get_foreign_keys(table_name)]
    return constraint_name in constraints


def upgrade() -> None:
    # Add columns only if they don't already exist (idempotent)
    if not _column_exists("routes", "driver_id"):
        op.add_column("routes", sa.Column("driver_id", sa.String(), nullable=True))
    if not _column_exists("routes", "vehicle_id"):
        op.add_column("routes", sa.Column("vehicle_id", sa.String(), nullable=True))
    if not _column_exists("routes", "pickup_time"):
        op.add_column("routes", sa.Column("pickup_time", sa.DateTime(timezone=True), nullable=True))
    if not _column_exists("routes", "planned_delivery_time"):
        op.add_column("routes", sa.Column("planned_delivery_time", sa.DateTime(timezone=True), nullable=True))
    
    # Create FK constraints only if they don't already exist
    if not _constraint_exists("fk_routes_driver_id", "routes"):
        op.create_foreign_key(
            "fk_routes_driver_id", "routes", "driver_master", ["driver_id"], ["driver_id"]
        )
    if not _constraint_exists("fk_routes_vehicle_id", "routes"):
        op.create_foreign_key(
            "fk_routes_vehicle_id", "routes", "vehicle_master", ["vehicle_id"], ["vehicle_id"]
        )


def downgrade() -> None:
    if _constraint_exists("fk_routes_vehicle_id", "routes"):
        op.drop_constraint("fk_routes_vehicle_id", "routes", type_="foreignkey")
    if _constraint_exists("fk_routes_driver_id", "routes"):
        op.drop_constraint("fk_routes_driver_id", "routes", type_="foreignkey")
    if _column_exists("routes", "planned_delivery_time"):
        op.drop_column("routes", "planned_delivery_time")
    if _column_exists("routes", "pickup_time"):
        op.drop_column("routes", "pickup_time")
    if _column_exists("routes", "vehicle_id"):
        op.drop_column("routes", "vehicle_id")
    if _column_exists("routes", "driver_id"):
        op.drop_column("routes", "driver_id")