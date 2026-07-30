"""add delay_predictions table

Revision ID: 1755ff316ef3
Revises:
Create Date: 2026-07-29 16:11:26.127451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '1755ff316ef3'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only the new table we own. autogenerate also proposed ALTER COLUMN
    # (TEXT->String, TIMESTAMP WITH TIME ZONE->DateTime - cosmetic SQLAlchemy
    # metadata differences, no real schema change) and new FK constraints on
    # the pre-existing production tables (trips/vehicle_master/driver_master/
    # etc.) - deliberately dropped from this migration. Those tables are
    # real production data we don't own; we only read from them here.
    op.create_table('delay_predictions',
    sa.Column('prediction_id', sa.UUID(), nullable=False),
    sa.Column('trip_id', sa.String(), nullable=False),
    sa.Column('delay_probability', sa.Float(), nullable=False),
    sa.Column('is_delayed_prediction', sa.Boolean(), nullable=False),
    sa.Column('model_version', sa.String(length=50), nullable=False),
    sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('predicted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.trip_id'], ),
    sa.PrimaryKeyConstraint('prediction_id')
    )


def downgrade() -> None:
    op.drop_table('delay_predictions')
