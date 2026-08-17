"""Dev launcher: run the FlowSense API without the Postgres-dependent lifespan.

The shipped lifespan calls Base.metadata.create_all on a live Postgres. When no
DB is available (e.g. verifying the stream proxy on a dev box) startup fails.
This launcher replaces the lifespan with a no-op so we can exercise non-DB
routes (stream, health, dashboard) directly. NOT for production -- production
must use main:app with a running Postgres.
"""
from contextlib import asynccontextmanager

from flowsense.api_server.main import app
import uvicorn


@asynccontextmanager
async def _noop(app):
    yield


app.router.lifespan_context = _noop

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8078, log_level="warning")
