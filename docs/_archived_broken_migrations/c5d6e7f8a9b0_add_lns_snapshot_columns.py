"""Add LNS before/after plan snapshots to optimization_runs.

Adds JSONB snapshot columns (routes_before / routes_after) plus the LNS
run details (trips_reinserted, destroy_strategy, repair_strategy) so the
Live Ops UI can render a Before ⇄ After impact comparison for every run.

Revision ID: c5d6e7f8a9b0
Revises: 8877aa1b2c3d
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "c5d6e7f8a9b0"
down_revision = "8877aa1b2c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("optimization_runs", sa.Column("trips_reinserted", sa.Integer(), nullable=True))
    op.add_column("optimization_runs", sa.Column("destroy_strategy", sa.String(length=30), nullable=True))
    op.add_column("optimization_runs", sa.Column("repair_strategy", sa.String(length=30), nullable=True))
    op.add_column("optimization_runs", sa.Column("routes_before", JSONB(), nullable=True))
    op.add_column("optimization_runs", sa.Column("routes_after", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("optimization_runs", "routes_after")
    op.drop_column("optimization_runs", "routes_before")
    op.drop_column("optimization_runs", "repair_strategy")
    op.drop_column("optimization_runs", "destroy_strategy")
    op.drop_column("optimization_runs", "trips_reinserted")