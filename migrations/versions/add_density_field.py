"""add density field

Revision ID: add_density_field
Revises: initial
Create Date: 2026-08-05 11:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'add_density_field'
down_revision: Union[str, None] = 'initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('detections', sa.Column('density', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('detections', 'density')
