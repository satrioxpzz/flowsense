"""Lane ROI loading and ground-point mapping."""
import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def load_rois(rois_path, camera_key: str) -> dict:
    path = Path(rois_path)
    if not path.exists():
        return {}
    rois = json.loads(path.read_text(encoding="utf-8"))
    cam_rois = rois.get(camera_key, {})
    return cam_rois


def scale_lanes(lanes: dict, original_size: tuple, current_size: tuple) -> dict:
    if not original_size or original_size == current_size:
        return lanes
    orig_w, orig_h = original_size
    curr_w, curr_h = current_size
    scale_x = curr_w / orig_w
    scale_y = curr_h / orig_h
    scaled_lanes = {}
    for name, poly in lanes.items():
        if name == "_resolution":
            continue
        scaled_lanes[name] = [[int(x * scale_x), int(y * scale_y)] for x, y in poly]
    return scaled_lanes


def point_in_poly(pt, poly) -> bool:
    if not poly or len(poly) < 3:
        return False
    return cv2.pointPolygonTest(np.array(poly, np.int32), pt, False) >= 0


def lane_from_detection(bbox, lanes) -> Optional[str]:
    """Map a detection to the lane containing its ground point (bbox bottom-center)."""
    bx1, _, bx2, by2 = bbox
    ground = ((bx1 + bx2) / 2.0, by2)
    for lane_name, poly in lanes.items():
        if point_in_poly(ground, poly):
            return lane_name
    return None
