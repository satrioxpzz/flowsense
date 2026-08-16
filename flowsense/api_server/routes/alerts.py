from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..schemas import AlertCreate, AlertResponse
from ...database.database import get_db
from ...database.models import Alert
from ...database.security import require_api_key

router = APIRouter()


@router.get("/", response_model=List[AlertResponse])
async def list_alerts(
    intersection_id: int = None,
    acknowledged: bool = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Return alerts with optional filters. Read-only."""
    stmt = select(Alert)
    if intersection_id is not None:
        stmt = stmt.where(Alert.intersection_id == intersection_id)
    if acknowledged is not None:
        stmt = stmt.where(Alert.acknowledged == acknowledged)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(Alert, alert_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return item


@router.post("/", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    alert: AlertCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Create a new alert. WRITE PROTECTED via X-API-Key (P0-6)."""
    item = Alert(**alert.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Acknowledge an alert. WRITE PROTECTED via X-API-Key (P0-6)."""
    item = await db.get(Alert, alert_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    item.acknowledged = True
    await db.commit()
    await db.refresh(item)
    return item
