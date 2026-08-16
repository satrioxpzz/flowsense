"""One-time backend scaffolding helper.

WARNING (P3-24): this script was used to bootstrap the backend and APPENDS to
requirements.txt / .env.example. Do NOT re-run it casually — it will duplicate
entries and overwrite hand-maintained setup. It is kept only for reference /
re-scaffolding on a clean checkout.
"""
import os
import pathlib
import sys

# P3-24: derive repo root from this file instead of a hardcoded path.
base_dir = pathlib.Path(__file__).resolve().parent

# Guard: refuse to run if the backend already looks scaffolded, to avoid
# clobbering manual fixes (e.g. the split requirements files).
if (base_dir / "flowsense" / "api_server").exists() and (base_dir / "requirements-api.txt").exists():
    print("Backend already scaffolded; refusing to re-run setup_backend.py "
          "to avoid overwriting manual changes. Exiting.", file=sys.stderr)
    sys.exit(1)

# Ensure base dir
os.makedirs(base_dir, exist_ok=True)

# 1. Update requirements.txt
req_path = base_dir / "requirements.txt"
reqs = "fastapi\nuvicorn[standard]\nsqlalchemy[asyncio]\nasyncpg\nalembic\npydantic\npython-jose[cryptography]\npasslib[bcrypt]\ngeoalchemy2\n"
if req_path.exists():
    with open(req_path, "a") as f:
        f.write("\n" + reqs)
else:
    with open(req_path, "w") as f:
        f.write(reqs)

# 2. Update .env.example
env_path = base_dir / ".env.example"
env_vars = "\nDATABASE_URL=postgresql+asyncpg://flowsense:flowsense@localhost:5432/flowsense\n"
if env_path.exists():
    with open(env_path, "a") as f:
        f.write(env_vars)
else:
    with open(env_path, "w") as f:
        f.write(env_vars)

# 3. Create database layer
db_dir = base_dir / "flowsense" / "database"
os.makedirs(db_dir, exist_ok=True)

with open(db_dir / "__init__.py", "w") as f:
    f.write("")

with open(db_dir / "database.py", "w") as f:
    f.write("""\
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://flowsense:flowsense@localhost:5432/flowsense")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
""")

with open(db_dir / "models.py", "w") as f:
    f.write("""\
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from .database import Base

class Camera(Base):
    __tablename__ = "cameras"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    url = Column(String)
    location_lat = Column(Float)
    location_lng = Column(Float)
    location = Column(Geometry('POINT'))
    status = Column(String, default="offline")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    detections = relationship("Detection", back_populates="camera")

class Detection(Base):
    __tablename__ = "detections"
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    total_vehicles = Column(Integer, default=0)
    per_lane = Column(JSON)
    crossings = Column(JSON)
    camera = relationship("Camera", back_populates="detections")

class Intersection(Base):
    __tablename__ = "intersections"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    location_lat = Column(Float)
    location_lng = Column(Float)
    location = Column(Geometry('POINT'))
    signal_config = Column(JSON)
    signals = relationship("TrafficSignal", back_populates="intersection")
    alerts = relationship("Alert", back_populates="intersection")

class TrafficSignal(Base):
    __tablename__ = "traffic_signals"
    id = Column(Integer, primary_key=True, index=True)
    intersection_id = Column(Integer, ForeignKey("intersections.id"))
    phase = Column(String)
    state = Column(String)
    duration = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    intersection = relationship("Intersection", back_populates="signals")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String)
    severity = Column(String)
    message = Column(String)
    intersection_id = Column(Integer, ForeignKey("intersections.id"))
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    intersection = relationship("Intersection", back_populates="alerts")
""")

# 4. Create API server layer
api_dir = base_dir / "flowsense" / "api_server"
routes_dir = api_dir / "routes"
os.makedirs(routes_dir, exist_ok=True)

with open(api_dir / "__init__.py", "w") as f:
    f.write("")

with open(api_dir / "schemas.py", "w") as f:
    f.write("""\
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Dict, Any, List

class CameraBase(BaseModel):
    name: str
    url: str
    location_lat: float
    location_lng: float
    status: Optional[str] = "offline"

class CameraCreate(CameraBase):
    pass

class CameraResponse(CameraBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class DetectionBase(BaseModel):
    camera_id: int
    timestamp: datetime
    total_vehicles: int
    per_lane: Dict[str, Any]
    crossings: Dict[str, Any]

class DetectionCreate(DetectionBase):
    pass

class DetectionResponse(DetectionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class IntersectionBase(BaseModel):
    name: str
    location_lat: float
    location_lng: float
    signal_config: Dict[str, Any]

class IntersectionCreate(IntersectionBase):
    pass

class IntersectionResponse(IntersectionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class TrafficSignalBase(BaseModel):
    intersection_id: int
    phase: str
    state: str
    duration: int

class TrafficSignalCreate(TrafficSignalBase):
    pass

class TrafficSignalResponse(TrafficSignalBase):
    id: int
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AlertBase(BaseModel):
    type: str
    severity: str
    message: str
    intersection_id: int

class AlertCreate(AlertBase):
    pass

class AlertResponse(AlertBase):
    id: int
    acknowledged: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
""")

with open(routes_dir / "__init__.py", "w") as f:
    f.write("""\
from fastapi import APIRouter
from . import cameras, detections, intersections, alerts, analytics, health

router = APIRouter()
router.include_router(cameras.router, prefix="/cameras", tags=["Cameras"])
router.include_router(detections.router, prefix="/detections", tags=["Detections"])
router.include_router(intersections.router, prefix="/intersections", tags=["Intersections"])
router.include_router(alerts.router, prefix="/alerts", tags=["Alerts"])
router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
router.include_router(health.router, prefix="/health", tags=["Health"])
""")

route_files = {
    "cameras.py": """\
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..schemas import CameraCreate, CameraResponse
from ...database.database import get_db
from ...database.models import Camera

router = APIRouter()

@router.post("/", response_model=CameraResponse)
async def create_camera(camera: CameraCreate, db: AsyncSession = Depends(get_db)):
    db_camera = Camera(**camera.model_dump())
    db.add(db_camera)
    await db.commit()
    await db.refresh(db_camera)
    return db_camera

@router.get("/", response_model=List[CameraResponse])
async def get_cameras(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera))
    return result.scalars().all()
""",
    "detections.py": """\
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from datetime import datetime
from ..schemas import DetectionCreate, DetectionResponse
from ...database.database import get_db
from ...database.models import Detection

router = APIRouter()

@router.post("/", response_model=DetectionResponse)
async def create_detection(detection: DetectionCreate, db: AsyncSession = Depends(get_db)):
    db_det = Detection(**detection.model_dump())
    db.add(db_det)
    await db.commit()
    await db.refresh(db_det)
    return db_det

@router.get("/", response_model=List[DetectionResponse])
async def get_detections(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Detection)
    if start_time:
        query = query.where(Detection.timestamp >= start_time)
    if end_time:
        query = query.where(Detection.timestamp <= end_time)
    result = await db.execute(query)
    return result.scalars().all()
""",
    "intersections.py": """\
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..schemas import IntersectionCreate, IntersectionResponse
from ...database.database import get_db
from ...database.models import Intersection

router = APIRouter()

@router.post("/", response_model=IntersectionResponse)
async def create_intersection(intersection: IntersectionCreate, db: AsyncSession = Depends(get_db)):
    db_item = Intersection(**intersection.model_dump())
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

@router.get("/", response_model=List[IntersectionResponse])
async def get_intersections(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Intersection))
    return result.scalars().all()
""",
    "alerts.py": """\
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..schemas import AlertCreate, AlertResponse
from ...database.database import get_db
from ...database.models import Alert

router = APIRouter()

@router.post("/", response_model=AlertResponse)
async def create_alert(alert: AlertCreate, db: AsyncSession = Depends(get_db)):
    db_item = Alert(**alert.model_dump())
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

@router.get("/", response_model=List[AlertResponse])
async def get_alerts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert))
    return result.scalars().all()
""",
    "analytics.py": """\
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ...database.database import get_db

router = APIRouter()

@router.get("/")
async def get_analytics(db: AsyncSession = Depends(get_db)):
    # Placeholder for aggregation logic
    return {"status": "analytics_endpoint_stub"}
""",
    "health.py": """\
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def health_check():
    return {"status": "ok"}
"""
}

for filename, content in route_files.items():
    with open(routes_dir / filename, "w") as f:
        f.write(content)

with open(api_dir / "main.py", "w") as f:
    f.write("""\
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import router
from ..database.database import engine, Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB (in production, use Alembic migrations instead)
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
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
""")

print("Setup complete")
