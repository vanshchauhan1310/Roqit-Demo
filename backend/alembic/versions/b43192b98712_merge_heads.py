"""merge_heads

Revision ID: b43192b98712
Revises: 1755ff316ef3, b7c8d9e0f1a2
Create Date: 2026-08-27 17:48:47.278884

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b43192b98712'
down_revision: Union[str, None] = ('1755ff316ef3', 'b7c8d9e0f1a2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
