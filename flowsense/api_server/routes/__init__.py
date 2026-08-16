from fastapi import APIRouter
from . import cameras, detections, intersections, alerts, analytics, health, dashboard

router = APIRouter()
router.include_router(cameras.router, prefix="/cameras", tags=["Cameras"])
router.include_router(detections.router, prefix="/detections", tags=["Detections"])
router.include_router(intersections.router, prefix="/intersections", tags=["Intersections"])
router.include_router(alerts.router, prefix="/alerts", tags=["Alerts"])
router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
router.include_router(health.router, prefix="/health", tags=["Health"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
