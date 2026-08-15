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
    crossings: Optional[Dict[str, Any]] = None
    density: Optional[Dict[str, Any]] = None
    pedestrians: Optional[int] = 0
    vision: Optional[List[Dict[str, Any]]] = None
    speeds: Optional[Dict[str, Any]] = None
    lane_avg_speeds: Optional[Dict[str, float]] = None
    anomalies: Optional[List[Dict[str, Any]]] = None
    signal_recommendations: Optional[List[Dict[str, Any]]] = None

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
