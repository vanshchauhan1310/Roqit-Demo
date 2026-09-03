"""add route_stops.trip_id column (link each stop to its trip)

Revision ID: 5f2b3c4d5e6f
Revises: 4f1a2b3c4d5e
Create Date: 2026-09-02

The RouteStop ORM model (backend/app/models/route.py) declares a trip_id column
(FK -> trips.trip_id) that links a route stop to the trip it fulfils.  This is
how the whole app decides which trips are already assigned to a route:

  - list_unassigned_trips: trips NOT IN (SELECT DISTINCT trip_id FROM route_stops)
  - sweep_unassigned_trips / TripAssignmentWorker: match trips to RouteStop rows
  - route_service / state.py: repair & validate assignment via RouteStop.trip_id

Migration a1b2c3d4e5f6 created route_stops without this column (the real
Supabase table it was based on had it, but that base revision 2a6f9c1d4b7e was
never committed).  On a fresh DB every one of those queries failed with
`column route_stops.trip_id does not exist`, 500ing GET /api/trips?unassigned
and breaking auto-assignment.

This migration adds the column to close the gap.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5f2b3c4d5e6f"
down_revision: Union[str, None] = "4f1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("route_stops", sa.Column("trip_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_route_stops_trip_id", "route_stops", "trips", ["trip_id"], ["trip_id"]
    )
    op.create_index("ix_route_stops_trip_id", "route_stops", ["trip_id"])


def downgrade() -> None:
    op.drop_index("ix_route_stops_trip_id", table_name="route_stops")
    op.drop_constraint("fk_route_stops_trip_id", "route_stops", type_="foreignkey")
    op.drop_column("route_stops", "trip_id")