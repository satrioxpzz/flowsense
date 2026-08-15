"""Traffic anomaly detection engine.

Detects: illegal parking, jaywalking, speeding, and accidents
by combining YOLO tracking data with speed estimates and lane ROIs.
"""
import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

log = logging.getLogger("flowsense.anomaly")


@dataclass
class Anomaly:
    """A detected traffic anomaly."""
    type: str           # "illegal_parking", "jaywalking", "speeding", "accident"
    severity: str       # "low", "medium", "high", "critical"
    track_id: Optional[int] = None
    lane: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class AnomalyDetector:
    """Stateful anomaly detector across consecutive frames."""
    
    def __init__(self, speed_limit: float = 60.0, 
                 parking_duration: float = 30.0,
                 accident_overlap_threshold: float = 0.5):
        self.speed_limit = speed_limit  # km/h
        self.parking_duration = parking_duration  # seconds before flagging
        self.accident_overlap_threshold = accident_overlap_threshold
        # {track_id: first_seen_stopped_timestamp}
        self._stopped_vehicles: Dict[int, float] = {}
        # {track_id: last_known_speed} for sudden-stop detection
        self._prev_speeds: Dict[int, float] = {}
    
    def detect_all(self, detections: list, speeds: Dict[int, float],
                   pedestrian_dets: list = None, lanes: dict = None,
                   now: float = None) -> List[Anomaly]:
        """Run all anomaly checks. Returns list of Anomaly objects."""
        if now is None:
            now = time.time()
        anomalies = []
        anomalies.extend(self._detect_speeding(detections, speeds))
        anomalies.extend(self._detect_illegal_parking(detections, speeds, now))
        anomalies.extend(self._detect_accidents(detections, speeds, now))
        if pedestrian_dets:
            anomalies.extend(self._detect_jaywalking(pedestrian_dets, lanes))
        # update previous speeds for next iteration
        self._prev_speeds = dict(speeds)
        return anomalies
    
    def _detect_speeding(self, detections: list, speeds: Dict[int, float]) -> List[Anomaly]:
        """Flag vehicles exceeding the speed limit."""
        results = []
        for det in detections:
            tid = det.get("track_id")
            if tid is None:
                continue
            spd = speeds.get(tid, 0.0)
            if spd > self.speed_limit:
                severity = "high" if spd > self.speed_limit * 1.5 else "medium"
                results.append(Anomaly(
                    type="speeding",
                    severity=severity,
                    track_id=tid,
                    lane=det.get("lane"),
                    details={"speed_kmh": spd, "limit_kmh": self.speed_limit,
                             "vehicle_type": det.get("type", "unknown")},
                ))
        return results
    
    def _detect_illegal_parking(self, detections: list, speeds: Dict[int, float],
                                 now: float) -> List[Anomaly]:
        """Flag vehicles that have been stationary too long."""
        results = []
        seen = set()
        for det in detections:
            tid = det.get("track_id")
            if tid is None:
                continue
            seen.add(tid)
            spd = speeds.get(tid, 0.0)
            if spd < 2.0:  # essentially stopped
                if tid not in self._stopped_vehicles:
                    self._stopped_vehicles[tid] = now
                elif now - self._stopped_vehicles[tid] >= self.parking_duration:
                    duration = now - self._stopped_vehicles[tid]
                    results.append(Anomaly(
                        type="illegal_parking",
                        severity="medium" if duration < 120 else "high",
                        track_id=tid,
                        lane=det.get("lane"),
                        details={"stopped_seconds": round(duration, 1),
                                 "vehicle_type": det.get("type", "unknown")},
                    ))
            else:
                # vehicle is moving again
                self._stopped_vehicles.pop(tid, None)
        # prune tracks no longer visible
        self._stopped_vehicles = {k: v for k, v in self._stopped_vehicles.items() if k in seen}
        return results
    
    def _detect_accidents(self, detections: list, speeds: Dict[int, float],
                          now: float) -> List[Anomaly]:
        """Detect potential accidents via sudden speed drops + bbox overlap."""
        results = []
        sudden_stops = []
        for det in detections:
            tid = det.get("track_id")
            if tid is None:
                continue
            cur_spd = speeds.get(tid, 0.0)
            prev_spd = self._prev_speeds.get(tid, 0.0)
            # sudden deceleration: was moving > 20 km/h, now < 3 km/h
            if prev_spd > 20.0 and cur_spd < 3.0:
                sudden_stops.append(det)
        
        # if 2+ vehicles suddenly stopped near each other, likely accident
        if len(sudden_stops) >= 2:
            for i, d1 in enumerate(sudden_stops):
                for d2 in sudden_stops[i+1:]:
                    if self._bboxes_overlap(d1["bbox"], d2["bbox"]):
                        results.append(Anomaly(
                            type="accident",
                            severity="critical",
                            lane=d1.get("lane"),
                            details={
                                "vehicle_1": {"track_id": d1.get("track_id"),
                                              "type": d1.get("type")},
                                "vehicle_2": {"track_id": d2.get("track_id"),
                                              "type": d2.get("type")},
                            },
                        ))
        return results
    
    def _detect_jaywalking(self, pedestrian_dets: list, lanes: dict) -> List[Anomaly]:
        """Flag pedestrians detected inside vehicle lanes (not at designated crossings).
        
        A simple heuristic: if a pedestrian's ground point is inside a vehicle
        lane polygon, they may be jaywalking. A proper implementation would
        also require zebra-cross ROI data.
        """
        if not lanes:
            return []
        from .lanes import lane_from_detection
        results = []
        for det in pedestrian_dets:
            lane = lane_from_detection(det["bbox"], lanes)
            if lane:  # pedestrian is inside a vehicle lane
                results.append(Anomaly(
                    type="jaywalking",
                    severity="medium",
                    track_id=det.get("track_id"),
                    lane=lane,
                    details={"pedestrian_in_lane": lane},
                ))
        return results
    
    @staticmethod
    def _bboxes_overlap(b1: list, b2: list) -> bool:
        """Check if two xyxy bounding boxes overlap."""
        x1 = max(b1[0], b2[0])
        y1 = max(b1[1], b2[1])
        x2 = min(b1[2], b2[2])
        y2 = min(b1[3], b2[3])
        if x2 <= x1 or y2 <= y1:
            return False
        inter = (x2 - x1) * (y2 - y1)
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        min_area = min(area1, area2)
        return (inter / min_area) > 0.3 if min_area > 0 else False
