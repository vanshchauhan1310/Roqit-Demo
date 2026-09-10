"""add trips.assigned_at

Revision ID: 7a8b9c0d1e2f
Revises: 5f2b3c4d5e6f
Create Date: 2026-09-02

Timestamp recorded when the assignment engine attaches a trip to a route.
The trip completion worker uses it to auto-complete a trip 10 minutes
after assignment (demo delivery lifecycle) and release the cargo weight
from the vehicle/route.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, None] = "5f2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("trips", "assigned_at")
