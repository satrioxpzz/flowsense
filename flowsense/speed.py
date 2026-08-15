"""Per-vehicle speed estimation from YOLO tracking data.

Approach: measure pixel displacement of tracked bounding boxes between
consecutive frames, convert to real-world speed using a calibration factor
(pixels-per-meter) and the stream's FPS.
"""
import time
from typing import Dict, Optional, Tuple

# Default calibration: approximate pixels-per-meter for a typical
# Kudus CCTV at ~6m mounting height, ~30° depression angle.
# Override per-camera via config/rois.json "calibration" key.
DEFAULT_PPM = 15.0  # pixels per meter
DEFAULT_FPS = 25.0
SMOOTHING_ALPHA = 0.4  # exponential moving average weight


class SpeedEstimator:
    """Track vehicles across frames and estimate their speed."""
    
    def __init__(self, ppm: float = DEFAULT_PPM, fps: float = DEFAULT_FPS):
        self.ppm = ppm
        self.fps = fps
        # {track_id: (last_center_x, last_center_y, last_timestamp, smoothed_speed_kmh)}
        self._tracks: Dict[int, Tuple[float, float, float, float]] = {}
        self._stale_threshold = 5.0  # seconds before dropping a track
    
    @staticmethod
    def _center(bbox: list) -> Tuple[float, float]:
        """Bottom-center of bbox (ground contact point)."""
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2, y2)
    
    def update(self, detections: list, now: float = None) -> Dict[int, float]:
        """Feed detections with track_id and bbox, return {track_id: speed_kmh}.
        
        Each detection dict must have 'track_id' and 'bbox' keys.
        Returns speeds only for vehicles seen in at least 2 consecutive frames.
        """
        if now is None:
            now = time.time()
        
        speeds = {}
        seen_ids = set()
        
        for det in detections:
            tid = det.get("track_id")
            if tid is None:
                continue
            seen_ids.add(tid)
            cx, cy = self._center(det["bbox"])
            
            prev = self._tracks.get(tid)
            if prev is not None:
                px, py, pt, prev_speed = prev
                dt = now - pt
                if dt > 0 and dt < self._stale_threshold:
                    # pixel displacement
                    dx = cx - px
                    dy = cy - py
                    pixel_dist = (dx**2 + dy**2) ** 0.5
                    # convert: pixels -> meters -> m/s -> km/h
                    meters = pixel_dist / self.ppm
                    m_per_s = meters / dt
                    kmh = m_per_s * 3.6
                    # exponential moving average for stability
                    smoothed = SMOOTHING_ALPHA * kmh + (1 - SMOOTHING_ALPHA) * prev_speed
                    speeds[tid] = round(smoothed, 1)
                    self._tracks[tid] = (cx, cy, now, smoothed)
                else:
                    # stale or zero dt, reset
                    self._tracks[tid] = (cx, cy, now, 0.0)
            else:
                # first sighting
                self._tracks[tid] = (cx, cy, now, 0.0)
        
        # prune stale tracks
        stale = [tid for tid, (_, _, t, _) in self._tracks.items()
                 if now - t > self._stale_threshold and tid not in seen_ids]
        for tid in stale:
            del self._tracks[tid]
        
        return speeds
    
    def get_lane_avg_speed(self, detections: list, speeds: Dict[int, float]) -> Dict[str, float]:
        """Compute average speed per lane from detections and their speeds."""
        lane_speeds: Dict[str, list] = {}
        for det in detections:
            tid = det.get("track_id")
            lane = det.get("lane")
            if tid is not None and lane and tid in speeds:
                lane_speeds.setdefault(lane, []).append(speeds[tid])
        return {lane: round(sum(s) / len(s), 1) for lane, s in lane_speeds.items() if s}
    
    def get_lane_queue_depth(self, detections: list, speeds: Dict[int, float],
                             stopped_threshold: float = 5.0) -> Dict[str, int]:
        """Count 'stopped' vehicles (speed < threshold) per lane as queue depth."""
        queues: Dict[str, int] = {}
        for det in detections:
            tid = det.get("track_id")
            lane = det.get("lane")
            if tid is not None and lane:
                spd = speeds.get(tid, 0.0)
                if spd < stopped_threshold:
                    queues[lane] = queues.get(lane, 0) + 1
        return queues
