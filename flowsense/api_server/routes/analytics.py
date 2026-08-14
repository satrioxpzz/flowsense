"""FlowSense Analytics aggregation endpoint for the city ops dashboard.

Replaces the previous stub (P0-9) with real aggregation queries against the
detections table: total/record counts, per-lane sums, and per-hour buckets for
peak/off-peak classification. Read-only.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import DetectionResponse
from ...database.database import get_db
from ...database.models import Detection

router = APIRouter()


@router.get("/", response_model=dict)
async def get_analytics(
    camera_id: int = Query(None, description="Restrict analytics to one camera"),
    window_hours: int = Query(24, ge=1, le=720, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate traffic analytics for the dashboard over the lookback window."""
    if window_hours <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="window_hours must be positive")
    since = datetime.utcnow() - timedelta(hours=window_hours)

    base = select(Detection).where(Detection.timestamp >= since)
    if camera_id is not None:
        base = base.where(Detection.camera_id == camera_id)

    records = (await db.execute(base.order_by(Detection.timestamp))).scalars().all()

    total_vehicles = sum(d.total_vehicles or 0 for d in records)
    per_lane_sum: dict[str, int] = {}
    per_hour: dict[str, int] = {}
    for d in records:
        lanes = d.per_lane or {}
        for lane, count in lanes.items():
            if isinstance(count, (int, float)):
                per_lane_sum[lane] = per_lane_sum.get(lane, 0) + int(count)
        hour_key = d.timestamp.strftime("%Y-%m-%dT%H:00") if d.timestamp else "unknown"
        per_hour[hour_key] = per_hour.get(hour_key, 0) + (d.total_vehicles or 0)

    counts = list(per_hour.values()) or [0]
    peak_hour = max(per_hour, key=per_hour.get) if per_hour else None

    return {
        "camera_id": camera_id,
        "window_hours": window_hours,
        "since": since.isoformat(),
        "total_vehicles": total_vehicles,
        "record_count": len(records),
        "per_lane_sum": per_lane_sum,
        "per_hour_counts": per_hour,
        "peak_hour": peak_hour,
        "average_per_record": round(total_vehicles / len(records), 2) if records else 0,
        "max_hourly_volume": max(counts),
        "min_hourly_volume": min(counts),
    }
