"""timezone-aware timestamp columns

Revision ID: timezone_aware_columns
Revises: add_density_field
Create Date: 2026-08-16 12:00:00.000000

P1-15: models previously used ``datetime.utcnow`` (naive, deprecated since
Python 3.12). Switch columns to timezone-aware ``TIMESTAMP WITH TIME ZONE`` and
store ``datetime.now(timezone.utc)``. Altering an existing column to tz-aware is
safe in Postgres (UTC values are preserved). Done idempotently so re-running
the migration is a no-op.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "timezone_aware_columns"
down_revision: Union[str, None] = "add_density_field"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column) pairs that must be timezone-aware
COLUMNS = [
    ("cameras", "created_at"),
    ("cameras", "updated_at"),
    ("detections", "timestamp"),
    ("traffic_signals", "updated_at"),
    ("users", "created_at"),
    ("alerts", "created_at"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, column in COLUMNS:
        cols = {c["name"]: c for c in inspector.get_columns(table)}
        if column not in cols:
            continue
        if cols[column].get("timezone"):
            continue  # already tz-aware
        # Convert to TIMESTAMP WITH TIME ZONE (UTC values preserved).
        op.execute(
            sa.text(
                f'ALTER TABLE {table} ALTER COLUMN {column} '
                f'TYPE timestamptz USING {column} AT TIME ZONE \'UTC\''
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, column in COLUMNS:
        cols = {c["name"]: c for c in inspector.get_columns(table)}
        if column not in cols:
            continue
        if not cols[column].get("timezone"):
            continue
        op.execute(
            sa.text(
                f'ALTER TABLE {table} ALTER COLUMN {column} '
                f'TYPE timestamp USING {column} AT TIME ZONE \'UTC\''
            )
        )
