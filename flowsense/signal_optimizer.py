"""Adaptive traffic signal duration optimizer.

Computes optimal green-phase duration per lane based on real-time
traffic metrics: vehicle speed, queue depth, and density.

Formula:
  base_green = (queue_depth / max_queue) * max_green
  speed_factor = 1.0 - (avg_speed / free_flow_speed)  
  # slower traffic = longer green needed
  green_time = clamp(base_green * (1 + speed_factor), min_green, max_green)
  
  If pedestrians with mobility aids detected: green += accessibility_extension
  If accident detected: force all-red
"""
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

log = logging.getLogger("flowsense.signal")


@dataclass
class SignalRecommendation:
    """Recommended signal timing for one lane/phase."""
    lane: str
    green_seconds: float
    reason: str
    priority: int = 0  # higher = more urgent (0=normal, 10=emergency)


class SignalOptimizer:
    """Compute adaptive green durations from live traffic data."""

    def __init__(self, min_green: float = 10.0, max_green: float = 50.0,
                 free_flow_speed: float = 50.0, max_queue: int = 30,
                 accessibility_extension: float = 15.0):
        self.min_green = min_green
        self.max_green = max_green
        self.free_flow_speed = free_flow_speed  # km/h
        self.max_queue = max_queue
        self.accessibility_ext = accessibility_extension

    def recommend(self, lane_avg_speeds: Dict[str, float],
                  lane_queue_depths: Dict[str, int],
                  lane_vehicle_counts: Dict[str, int],
                  accessibility_lanes: Optional[List[str]] = None,
                  accident_lanes: Optional[List[str]] = None) -> List[SignalRecommendation]:
        """Generate signal timing recommendations for all lanes."""
        recommendations = []

        # accident override: all-red
        if accident_lanes:
            for lane in accident_lanes:
                recommendations.append(SignalRecommendation(
                    lane=lane,
                    green_seconds=0.0,
                    reason=f"ACCIDENT detected in {lane} — force ALL RED",
                    priority=10,
                ))
            # all other lanes also get red
            all_lanes = set(lane_vehicle_counts.keys()) | set(lane_queue_depths.keys())
            for lane in all_lanes - set(accident_lanes):
                recommendations.append(SignalRecommendation(
                    lane=lane,
                    green_seconds=0.0,
                    reason="ALL RED due to accident on adjacent lane",
                    priority=10,
                ))
            return recommendations

        all_lanes = set(lane_vehicle_counts.keys()) | set(lane_queue_depths.keys())
        for lane in all_lanes:
            queue = lane_queue_depths.get(lane, 0)
            avg_speed = lane_avg_speeds.get(lane, self.free_flow_speed)
            count = lane_vehicle_counts.get(lane, 0)

            # base green from queue proportion
            queue_ratio = min(queue / self.max_queue, 1.0) if self.max_queue > 0 else 0.0
            base_green = self.min_green + queue_ratio * (self.max_green - self.min_green)

            # speed factor: slower traffic needs more green
            speed_ratio = max(0.0, min(avg_speed / self.free_flow_speed, 1.0))
            speed_factor = 1.0 + (1.0 - speed_ratio) * 0.5  # up to 50% longer

            green = base_green * speed_factor

            # density bonus: if lane has many vehicles, extend slightly
            if count > 10:
                green *= 1.15

            # clamp
            green = max(self.min_green, min(green, self.max_green))

            reason = (f"queue={queue}, avg_speed={avg_speed:.0f}km/h, "
                      f"vehicles={count}")

            # accessibility extension
            if accessibility_lanes and lane in accessibility_lanes:
                green = min(green + self.accessibility_ext, self.max_green + self.accessibility_ext)
                reason += ", +accessibility extension"

            recommendations.append(SignalRecommendation(
                lane=lane,
                green_seconds=round(green, 1),
                reason=reason,
                priority=1 if queue > 15 else 0,
            ))

        # sort by priority descending, then by green_seconds descending
        recommendations.sort(key=lambda r: (-r.priority, -r.green_seconds))
        return recommendations
