from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import DetectionCreate, DetectionResponse
from ...database.database import get_db
from ...database.models import Detection
from ...database.security import require_api_key

router = APIRouter()


@router.get("/", response_model=List[DetectionResponse])
async def list_detections(
    camera_id: Optional[int] = Query(None, description="Filter by camera id"),
    start_time: Optional[datetime] = Query(None, description="Lower bound (inclusive)"),
    end_time: Optional[datetime] = Query(None, description="Upper bound (inclusive)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Return detections with optional camera/time filters. Read-only."""
    stmt = select(Detection)
    if camera_id is not None:
        stmt = stmt.where(Detection.camera_id == camera_id)
    if start_time is not None:
        stmt = stmt.where(Detection.timestamp >= start_time)
    if end_time is not None:
        stmt = stmt.where(Detection.timestamp <= end_time)
    stmt = stmt.order_by(Detection.timestamp.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{detection_id}", response_model=DetectionResponse)
async def get_detection(detection_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(Detection, detection_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")
    return item


@router.post("/", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    detection: DetectionCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Ingest a new detection record. WRITE PROTECTED via X-API-Key (P0-6)."""
    item = Detection(**detection.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/stats/summary", response_model=dict)
async def detection_summary(
    camera_id: Optional[int] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate total vehicle counts for the city ops dashboard."""
    stmt = select(func.coalesce(func.sum(Detection.total_vehicles), 0))
    count_stmt = select(func.count()).select_from(Detection)
    if camera_id is not None:
        stmt = stmt.where(Detection.camera_id == camera_id)
        count_stmt = count_stmt.where(Detection.camera_id == camera_id)
    if start_time is not None:
        stmt = stmt.where(Detection.timestamp >= start_time)
        count_stmt = count_stmt.where(Detection.timestamp >= start_time)
    if end_time is not None:
        stmt = stmt.where(Detection.timestamp <= end_time)
        count_stmt = count_stmt.where(Detection.timestamp <= end_time)

    total_vehicles = (await db.execute(stmt)).scalar_one()
    record_count = (await db.execute(count_stmt)).scalar_one()
    return {
        "camera_id": camera_id,
        "total_vehicles": int(total_vehicles),
        "record_count": int(record_count),
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
    }
