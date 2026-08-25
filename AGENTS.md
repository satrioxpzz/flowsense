# Project: FlowSense
# Description: Edge vehicle detection for CCTV streams with YOLOv11 and FastAPI backend.

- The complete project architecture, tech stack, and conventions are documented in `MEMORY.md`.
- Read `MEMORY.md` to gain full context on this project before making significant architectural changes.
- Project uses Python 3.13.
- Core inference pipeline is in `flowsense/runner.py` (the connector entry point `connector.py` is a thin CLI wrapper that calls it).
- Backend API uses FastAPI and SQLAlchemy (Async) located under `flowsense/`.
- Ensure new backend models inherit from `Base` in `flowsense/database/database.py` and have appropriate async routes.
- When generating SQL/Database changes, remember that it utilizes `asyncpg` and `GeoAlchemy2`.
