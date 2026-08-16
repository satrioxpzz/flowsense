"""initial schema

Revision ID: initial
Revises:
Create Date: 2026-08-04 16:59:00.000000

Creates the full application schema (cameras, detections, intersections,
traffic_signals, users, alerts) directly from the SQLAlchemy models so the
migrated database exactly matches ``flowsense.database.models``.

This replaces the previous no-op stub (which only contained a ``pass`` and
left every endpoint failing with ``UndefinedTableError``).

"""

from typing import Sequence, Union

from alembic import op

from flowsense.database.database import Base
from flowsense.database.models import (  # noqa: F401  (ensure models are registered)
    Alert,
    Camera,
    Detection,
    Intersection,
    TrafficSignal,
    User,
)

revision: str = "initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
