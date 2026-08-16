"""YOLO detection wrapper and frame summarization.

P2-3 fix: class filtering is now name-based, derived from the loaded model's
``model.names`` at runtime (via ``results.names``), instead of hardcoding COCO
class indices. This means a custom-trained model with different class indices
no longer silently counts the wrong classes.
"""
from typing import Dict, List, Optional, Tuple

from .lanes import lane_from_detection

# Canonical vehicle/pedestrian class *names* (lowercased). Exact COCO spelling
# for the pretrained weights; a custom model just needs the same names.
VEHICLE_CLASS_NAMES = {"bicycle", "car", "motorcycle", "bus", "truck"}
PEDESTRIAN_CLASS_NAMES = {"person", "pedestrian"}

# Kept for backward compatibility / reference only. Do NOT use these to filter
# detections — see P2-3.
VEHICLE_CLASSES_COCO = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


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


def _class_name(results_names: Dict[int, str], cls: int) -> str:
    """Resolve a class index to its (lowercased) name from the model's names map."""
    return results_names.get(int(cls), "").lower()


def _detections(results, min_conf):
    """Yield (cls, conf, bbox, name) for vehicle boxes above min_conf.

    Class membership is decided by the model's own ``names`` map (P2-3), so the
    same code works for COCO-pretrained and custom-trained weights.
    """
    for r in results:
        names = r.names
        for box in r.boxes:
            cls = int(box.cls[0])
            name = _class_name(names, cls)
            if name not in VEHICLE_CLASS_NAMES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            yield cls, conf, [float(x) for x in box.xyxy[0]], name


def summarize_frame(results, lanes, min_conf: float = 0.35) -> dict:
    counts = {name: 0 for name in lanes}
    vehicles = []
    for cls, conf, bbox, name in _detections(results, min_conf):
        det = {
            "bbox": bbox,
            "cls": cls,
            "type": name,
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
        names = r.names
        for box in r.boxes:
            cls = int(box.cls[0])
            name = _class_name(names, cls)
            if name not in VEHICLE_CLASS_NAMES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            bbox = [float(x) for x in box.xyxy[0]]
            lane = lane_from_detection(bbox, lanes)
            det = {
                "bbox": bbox,
                "cls": cls,
                "type": name,
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
    """Extract pedestrian detections (name "person"/"pedestrian") for the vision side.

    Returns det dicts with bbox, cls, type="pedestrian", conf, lane and, when
    tracking is active, track_id. Persons are excluded from the vehicle
    counters in summarize_frame / track_summary.
    """
    dets = []
    for r in results:
        names = r.names
        for box in r.boxes:
            cls = int(box.cls[0])
            name = _class_name(names, cls)
            if name not in PEDESTRIAN_CLASS_NAMES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            bbox = [float(x) for x in box.xyxy[0]]
            det = {
                "bbox": bbox,
                "cls": cls,
                "type": "pedestrian",
                "conf": conf,
                "lane": lane_from_detection(bbox, lanes),
            }
            tid = int(box.id[0]) if box.id is not None else None
            if tid is not None:
                det["track_id"] = tid
            dets.append(det)
    return dets
