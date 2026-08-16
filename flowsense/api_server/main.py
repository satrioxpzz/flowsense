from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import router
from ..database.database import engine, Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic is the source of truth for schema in production. As a safety
    # net (dev / first boot) we ensure the tables exist so the API never
    # fails with UndefinedTableError when started without running migrations.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="FlowSense API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Explicit allow-list from the environment. "*" is NEVER combined with
    # allow_credentials=True (browsers reject that combination, and it is the
    # most permissive possible config). Leave FLOWSENSE_CORS_ORIGINS empty to
    # disable cross-origin access entirely (recommended for an internal API).
    allow_origins=[
        o.strip()
        for o in os.getenv("FLOWSENSE_CORS_ORIGINS", "").split(",")
        if o.strip()
    ],
    allow_credentials=bool(os.getenv("FLOWSENSE_CORS_ORIGINS", "").strip()),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
