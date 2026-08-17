"""FlowSense detector eval harness.

Two modes:

1. INFERENCE DIAGNOSTIC (default, no labels needed)
   Runs the YOLO model over a set of frames and reports, per class:
     - box count
     - confidence min / mean / max
     - a count of low-confidence (< min_conf) detections that were *dropped*
   Writes an annotated copy of each frame to <out>/annotated/.
   This is the only eval possible until a labeled test set exists.

2. SUPERVISED VAL (--data data.yaml)
   Runs YOLO model.val() against a YOLO-format labeled dataset and prints
   real mAP / precision / recall / F1 + a confusion matrix. This is the
   authoritative accuracy number and should be run the moment a labeled
   cvat_dataset is produced (see capture_frames.py -> CVAT -> export YOLO).

Usage:
  # diagnostic on the committed test frame + any frames under data/frames_eval
  python -m scripts.eval_detector --frames data/frame_test.jpg --out output/eval

  # supervised, once labels exist
  python -m scripts.eval_detector --data data/cvat_dataset/data.yaml --out output/eval
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

# Match detector.py: only these classes matter to FlowSense, and the harness
# reports on them explicitly (plus pedestrians, which the vision path consumes).
VEHICLE_CLASS_NAMES = {"bicycle", "car", "motorcycle", "bus", "truck"}
PEDESTRIAN_CLASS_NAMES = {"person", "pedestrian"}


def _load_model(model_path: str):
    from ultralytics import YOLO
    import torch
    model = YOLO(model_path)
    if torch.cuda.is_available():
        model.to("cuda")
    return model


def run_diagnostic(model, frames, out_dir: Path, min_conf: float, imgsz: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir = out_dir / "annotated"
    annotated_dir.mkdir(parents=True, exist_ok=True)

    stats = defaultdict(lambda: {"kept": 0, "dropped": 0,
                                 "conf_kept": [], "conf_dropped": []})
    total_frames = 0
    total_kept = 0
    total_dropped = 0

    for fr in frames:
        img = cv2.imread(str(fr))
        if img is None:
            print(f"  skip (unreadable): {fr}")
            continue
        total_frames += 1
        results = model(img, conf=0.01, iou=0.5, verbose=False, imgsz=imgsz)[0]
        names = {int(k): v for k, v in results.names.items()}

        vis = img.copy()
        for box in results.boxes:
            cls = int(box.cls[0])
            name = names.get(cls, "").lower()
            conf = float(box.conf[0])
            if name not in VEHICLE_CLASS_NAMES and name not in PEDESTRIAN_CLASS_NAMES:
                continue
            kept = conf >= min_conf
            bucket = stats[name]
            if kept:
                bucket["kept"] += 1
                bucket["conf_kept"].append(conf)
                total_kept += 1
                color = (0, 200, 0)
            else:
                bucket["dropped"] += 1
                bucket["conf_dropped"].append(conf)
                total_dropped += 1
                color = (0, 0, 200)
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            cv2.putText(vis, f"{name} {conf:.2f}",
                        (x1, max(0, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, color, 1)

        cv2.imwrite(str(annotated_dir / fr.name), vis)
        print(f"  {fr.name}: {len(results.boxes)} boxes -> "
              f"{sum(1 for b in results.boxes if float(b.conf[0]) >= min_conf)} kept "
              f"({sum(1 for b in results.boxes if float(b.conf[0]) < min_conf)} dropped)")

    report = {
        "mode": "inference_diagnostic",
        "frames": total_frames,
        "min_conf": min_conf,
        "imgsz": imgsz,
        "total_kept": total_kept,
        "total_dropped_below_conf": total_dropped,
        "per_class": {},
    }
    for name, b in sorted(stats.items()):
        kc, dc = b["conf_kept"], b["conf_dropped"]
        report["per_class"][name] = {
            "kept": b["kept"],
            "dropped_below_conf": b["dropped"],
            "conf_kept": {
                "min": round(min(kc), 3) if kc else None,
                "mean": round(float(np.mean(kc)), 3) if kc else None,
                "max": round(max(kc), 3) if kc else None,
            },
            "conf_dropped": {
                "min": round(min(dc), 3) if dc else None,
                "mean": round(float(np.mean(dc)), 3) if dc else None,
                "max": round(max(dc), 3) if dc else None,
            },
            "note": ("OUTSIDE FlowSense vehicle/pedestrian set -- would be ignored by detector"
                     if name not in VEHICLE_CLASS_NAMES and name not in PEDESTRIAN_CLASS_NAMES
                     else "counted by FlowSense"),
        }

    (out_dir / "report_diagnostic.json").write_text(json.dumps(report, indent=2))
    return report


def run_val(model, data_yaml: Path, out_dir: Path, min_conf: float, imgsz: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = model.val(
        data=str(data_yaml),
        split="val",
        conf=min_conf,
        iou=0.5,
        imgsz=imgsz,
        verbose=False,
        project=str(out_dir),
        name="val",
        device="0" if __import__("torch").cuda.is_available() else "cpu",
    )
    report = {
        "mode": "supervised_val",
        "data": str(data_yaml),
        "min_conf": min_conf,
        "imgsz": imgsz,
        "metrics": {
            "mAP50": round(float(metrics.box.map50), 4),
            "mAP50-95": round(float(metrics.box.map), 4),
            "precision": round(float(metrics.box.mp), 4),
            "recall": round(float(metrics.box.mr), 4),
        },
    }
    (out_dir / "report_val.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="FlowSense YOLO detector eval harness")
    ap.add_argument("--model", default="yolo11n.pt", help="YOLO weights")
    ap.add_argument("--frames", nargs="*", help="frame paths for diagnostic mode")
    ap.add_argument("--frames-dir", help="directory to glob for *.jpg/*.png (diagnostic)")
    ap.add_argument("--data", help="YOLO data.yaml for supervised val mode")
    ap.add_argument("--out", default="output/eval", help="output dir")
    ap.add_argument("--min-conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    model = _load_model(args.model)

    if args.data:
        if not Path(args.data).exists():
            print(f"ERROR: --data {args.data} not found. "
                  "Produce labels first (capture_frames.py -> CVAT -> export YOLO).")
            return 2
        rep = run_val(model, Path(args.data), out_dir, args.min_conf, args.imgsz)
        print(json.dumps(rep, indent=2))
        return 0

    frames = []
    if args.frames:
        frames += [Path(f) for f in args.frames]
    if args.frames_dir:
        d = Path(args.frames_dir)
        frames += list(d.glob("*.jpg")) + list(d.glob("*.png"))
    if not frames:
        print("ERROR: no frames and no --data. Provide --frames/--frames-dir "
              "for the diagnostic, or --data data.yaml for supervised val.")
        return 2

    print(f"Diagnostic over {len(frames)} frame(s) at min_conf={args.min_conf}...")
    rep = run_diagnostic(model, frames, out_dir, args.min_conf, args.imgsz)
    print(json.dumps(rep, indent=2))
    print(f"\nAnnotated frames -> {out_dir / 'annotated'}")
    print(f"Report           -> {out_dir / 'report_diagnostic.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
