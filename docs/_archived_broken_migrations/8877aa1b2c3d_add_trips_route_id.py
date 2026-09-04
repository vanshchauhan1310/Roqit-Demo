"""add_trips_route_id

Revision ID: 8877aa1b2c3d
Revises: a86ca6923361
Create Date: 2026-08-28 12:00:00.000000

Adds the denormalized `route_id` column to `trips` so the optimization engine
can cheaply check/clear a trip's route assignment (used by greedy insertion,
new-route creation and the LNS destroy/rollback phases).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8877aa1b2c3d'
down_revision: Union[str, None] = 'a86ca6923361'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("route_id", sa.String(), nullable=True))
    op.create_index("ix_trips_route_id", "trips", ["route_id"])


def downgrade() -> None:
    op.drop_index("ix_trips_route_id", table_name="trips")
    op.drop_column("trips", "route_id")