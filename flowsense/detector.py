"""YOLO detection wrapper and frame summarization."""
from typing import List, Optional, Tuple

from .lanes import lane_from_detection

VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PEDESTRIAN_CLASSES = {0: "pedestrian"}


def load_model(model_path: str):
    """Lazy ultralytics import so unit tests run without it installed."""
    import os
    import torch
    from ultralytics import YOLO

    # Allow duplicate OpenMP libraries (conda + pytorch)
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
    
    model = YOLO(model_path)
    # Move model to GPU if available
    if torch.cuda.is_available():
        model.to('cuda')
    return model


def _detections(results, min_conf):
    """Yield (cls, conf, bbox) for vehicle boxes above min_conf."""
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls not in VEHICLE_CLASSES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            yield cls, conf, [float(x) for x in box.xyxy[0]]


def summarize_frame(results, lanes, min_conf: float = 0.35) -> dict:
    counts = {name: 0 for name in lanes}
    vehicles = []
    for cls, conf, bbox in _detections(results, min_conf):
        det = {
            "bbox": bbox,
            "cls": cls,
            "type": VEHICLE_CLASSES[cls],
            "conf": conf,
            "lane": lane_from_detection(bbox, lanes),
        }
        vehicles.append(det)
        if det["lane"]:
            counts[det["lane"]] += 1
    return {
        "total_vehicles": len(vehicles),
        "per_lane": counts,
        "vehicles": vehicles,
    }


def track_summary(results, lanes, min_conf: float = 0.35) -> Tuple[List[dict], List[Tuple[int, Optional[str]]]]:
    """Tracked-mode summarization. Returns (dets, [(track_id, lane)]) pairs."""
    dets = []
    pairs = []
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls not in VEHICLE_CLASSES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            bbox = [float(x) for x in box.xyxy[0]]
            lane = lane_from_detection(bbox, lanes)
            det = {
                "bbox": bbox,
                "cls": cls,
                "type": VEHICLE_CLASSES[cls],
                "conf": conf,
                "lane": lane,
            }
            tid = int(box.id[0]) if box.id is not None else None
            if tid is not None:
                det["track_id"] = tid
                pairs.append((tid, lane))
            dets.append(det)
    return dets, pairs


def pedestrian_detections(results, lanes, min_conf: float = 0.35) -> List[dict]:
    """Extract pedestrian detections (COCO class 0) for the vision side.

    Returns det dicts with bbox, cls, type="pedestrian", conf, lane and, when
    tracking is active, track_id. Persons are excluded from the vehicle
    counters in summarize_frame / track_summary.
    """
    dets = []
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls not in PEDESTRIAN_CLASSES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            bbox = [float(x) for x in box.xyxy[0]]
            det = {
                "bbox": bbox,
                "cls": cls,
                "type": PEDESTRIAN_CLASSES[cls],
                "conf": conf,
                "lane": lane_from_detection(bbox, lanes),
            }
            tid = int(box.id[0]) if box.id is not None else None
            if tid is not None:
                det["track_id"] = tid
            dets.append(det)
    return dets
