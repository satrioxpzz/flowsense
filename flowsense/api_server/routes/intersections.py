from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Annotated, List

from ..schemas import IntersectionCreate, IntersectionResponse
from ...database.database import get_db
from ...database.models import Intersection
from ...database.security import require_api_key

router = APIRouter()


@router.post("/", response_model=IntersectionResponse, status_code=status.HTTP_201_CREATED)
async def create_intersection(
    intersection: IntersectionCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Create an intersection. WRITE PROTECTED via X-API-Key (P0-6)."""
    item = Intersection(**intersection.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/", response_model=List[IntersectionResponse])
async def get_intersections(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Intersection).order_by(Intersection.id))
    return result.scalars().all()
