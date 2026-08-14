#!/usr/bin/env python3
"""FlowSense Database initialization / migration helper (P0-2).

Creates the schema for all SQLAlchemy models against the configured database
and, optionally, stamps an initial Alembic revision so the schema stays under
migration control in production.

Usage:
    pip install -r requirements.txt
    export DATABASE_URL="postgresql+asyncpg://postgres:flowsense@localhost:5432/flowsense"
    cd /path/to/flowsense
    python scripts/init_database.py              # create tables
    python scripts/init_database.py --revision   # also generate + stamp an alembic migration
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Make the repo root importable when run as a standalone script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    """Best-effort load of .env so DATABASE_URL is available without exports."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        # dotenv is optional in this helper; DATABASE_URL may already be in env.
        pass


async def create_tables() -> None:
    """Create all tables via the application's init_db() (P0-2)."""
    from flowsense.database.database import engine, init_db

    print("Creating schema via init_db()...")
    await init_db()
    async with engine.connect() as conn:
        from sqlalchemy import inspect

        tables = await conn.run_sync(
            lambda c: inspect(c).get_table_names()
        )
    print(f"Schema ready. Tables present: {len(tables)}")
    await engine.dispose()


def run_alembic() -> int:
    """Generate (if requested) and stamp the initial Alembic migration.

    Returns the subprocess exit code.
    """
    import subprocess

    if not (ROOT / "alembic.ini").exists():
        print("alembic.ini not found; skipping alembic step.")
        return 0

    # Stamp head if migrations already exist; otherwise autogenerate first.
    versions = list((ROOT / "migrations" / "versions").glob("*.py")) if (ROOT / "migrations").exists() else []
    if not versions:
        print("No migration versions found; generating initial autogeneration...")
        gen = subprocess.run(
            ["alembic", "revision", "--autogenerate", "-m", "initial schema"],
            cwd=str(ROOT),
        )
        if gen.returncode != 0:
            return gen.returncode

    stamp = subprocess.run(["alembic", "stamp", "head"], cwd=str(ROOT))
    return stamp.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize FlowSense database schema.")
    parser.add_argument(
        "--revision",
        action="store_true",
        help="Also generate/stamp an Alembic migration after creating tables.",
    )
    args = parser.parse_args()

    _load_env()

    if not __import__("os").environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL is not set. Export it or add it to .env.")
        return 2

    asyncio.run(create_tables())

    if args.revision:
        return run_alembic()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
