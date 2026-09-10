"""add missing route assignment columns (driver_id, vehicle_id, pickup_time, planned_delivery_time)

Revision ID: 4f1a2b3c4d5e
Revises: 3bd8ab2c9348
Create Date: 2026-09-02

The Route ORM model (backend/app/models/route.py) declares driver_id, vehicle_id,
pickup_time, and planned_delivery_time - matching the "real" Supabase routes table
that was created by the lost revision 2a6f9c1d4b7e (never committed to this repo).

On a fresh docker DB the routes table comes from a1b2c3d4e5f6, which omitted these
four columns, so every code path that assigns a driver/vehicle or reads those
fields fails with "column routes.driver_id does not exist" (e.g. the LNS worker,
route_service, roster_service, and the Live Ops route tables).

This migration closes the gap so a fresh-bootstrap schema matches the ORM.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f1a2b3c4d5e"
down_revision: Union[str, None] = "3bd8ab2c9348"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("driver_id", sa.String(), nullable=True))
    op.add_column("routes", sa.Column("vehicle_id", sa.String(), nullable=True))
    op.add_column("routes", sa.Column("pickup_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("routes", sa.Column("planned_delivery_time", sa.DateTime(timezone=True), nullable=True))
    # Match the FK constraints the ORM model declares.
    op.create_foreign_key(
        "fk_routes_driver_id", "routes", "driver_master", ["driver_id"], ["driver_id"]
    )
    op.create_foreign_key(
        "fk_routes_vehicle_id", "routes", "vehicle_master", ["vehicle_id"], ["vehicle_id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_routes_vehicle_id", "routes", type_="foreignkey")
    op.drop_constraint("fk_routes_driver_id", "routes", type_="foreignkey")
    op.drop_column("routes", "planned_delivery_time")
    op.drop_column("routes", "pickup_time")
    op.drop_column("routes", "vehicle_id")
    op.drop_column("routes", "driver_id")