"""add weather_condition/weather_updated_at to route_stops

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-30 16:00:00.000000

Adds two nullable columns to route_stops (a table this app owns/created,
not one of the CSV-imported tables) — safe, additive-only change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("route_stops", sa.Column("weather_condition", sa.String(length=50), nullable=True))
    op.add_column("route_stops", sa.Column("weather_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("route_stops", "weather_updated_at")
    op.drop_column("route_stops", "weather_condition")
