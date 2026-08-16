"""add density field

Revision ID: add_density_field
Revises: initial
Create Date: 2026-08-05 11:00:00.000000

Historically added a ``density`` JSON column to ``detections``. The column is
now created unconditionally by the ``initial`` migration, so this step only
adds it when missing (idempotent) to stay safe on databases migrated with the
old no-op ``initial``.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_density_field"
down_revision: Union[str, None] = "initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("detections")}
    if "density" not in existing:
        op.add_column("detections", sa.Column("density", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("detections")}
    if "density" in existing:
        op.drop_column("detections", "density")
