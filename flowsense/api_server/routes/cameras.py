from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from ..schemas import CameraCreate, CameraResponse
from ...database.database import get_db
from ...database.models import Camera
from ...database.security import require_api_key

router = APIRouter()


@router.get("/", response_model=List[CameraResponse])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    """Return all registered cameras (read-only, no auth required)."""
    result = await db.execute(select(Camera).order_by(Camera.id))
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(Camera, camera_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return item


@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    camera: CameraCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Register a new camera. WRITE PROTECTED via X-API-Key (P0-6)."""
    item = Camera(**camera.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int,
    camera: CameraCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Update an existing camera. WRITE PROTECTED via X-API-Key (P0-6)."""
    item = await db.get(Camera, camera_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    for field, value in camera.model_dump().items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Delete a camera. WRITE PROTECTED via X-API-Key (P0-6)."""
    item = await db.get(Camera, camera_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    await db.delete(item)
    await db.commit()
