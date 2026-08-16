from contextlib import asynccontextmanager
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
