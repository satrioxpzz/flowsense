from enum import Enum
from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, Dict, Any, List

# P2-17: constrained enums instead of free-form str for status-like fields.
class AlertSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

class SignalPhase(str, Enum):
    red = "red"
    yellow = "yellow"
    green = "green"

class CameraBase(BaseModel):
    name: str
    url: str
    # P2-17: validate coordinates are within valid WGS84 ranges.
    location_lat: float
    location_lng: float
    status: Optional[str] = "offline"

    @field_validator("location_lat")
    @classmethod
    def _check_lat(cls, v):
        if not -90.0 <= v <= 90.0:
            raise ValueError("location_lat must be between -90 and 90")
        return v

    @field_validator("location_lng")
    @classmethod
    def _check_lng(cls, v):
        if not -180.0 <= v <= 180.0:
            raise ValueError("location_lng must be between -180 and 180")
        return v

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
    # P2-17: crossings already optional (edge omits it in non-tracking mode).
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

    @field_validator("location_lat")
    @classmethod
    def _check_lat(cls, v):
        if not -90.0 <= v <= 90.0:
            raise ValueError("location_lat must be between -90 and 90")
        return v

    @field_validator("location_lng")
    @classmethod
    def _check_lng(cls, v):
        if not -180.0 <= v <= 180.0:
            raise ValueError("location_lng must be between -180 and 180")
        return v

class IntersectionCreate(IntersectionBase):
    pass

class IntersectionResponse(IntersectionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class TrafficSignalBase(BaseModel):
    intersection_id: int
    phase: SignalPhase
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
    severity: AlertSeverity
    message: str
    intersection_id: int

class AlertCreate(AlertBase):
    pass

class AlertResponse(AlertBase):
    id: int
    acknowledged: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
