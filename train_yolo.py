"""Fine-tune a FlowSense vehicle detector on labeled Kudus CCTV data.

Replaces the old root train_yolo.py (which pointed at a non-existent
data/cvat_dataset/data.yaml and had dead imports). The class set is
derived from data.yaml's `names` at train time -- train on whatever CVAT
exports. FlowSense's detector.py maps by NAME at inference, so a custom
model's indices don't matter as long as the names match VEHICLE_CLASS_NAMES.

Pipeline:
  1. scripts/grab_label_frames.py   -> raw frames
  2. CVAT: annotate, export YOLO txt -> data/cvat_dataset/labels/{train,val}
  3. python train_yolo.py            -> runs/train/flowsense_yoloN
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Fine-tune YOLO for FlowSense")
    parser.add_argument("--data", type=str,
                        default=str(here / "data" / "cvat_dataset" / "data.yaml"),
                        help="YOLO dataset yaml (must exist, with names + train/val paths)")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--weights", type=str, default="yolo11n.pt",
                        help="Base weights (n=s fast, m/l better but heavier)")
    parser.add_argument("--name", type=str, default="flowsense_yolo")
    args = parser.parse_args()

    data_yaml = Path(args.data)
    if not data_yaml.exists():
        print(f"ERROR: dataset yaml not found: {data_yaml}\n"
              "Run scripts/grab_label_frames.py, label in CVAT, "
              "export YOLO labels, then create data.yaml (see "
              "data/cvat_dataset/label_guide.md).")
        return 2

    print(f"Loading base model: {args.weights}")
    model = YOLO(args.weights)

    print(f"Training on {data_yaml} for {args.epochs} epochs (imgsz={args.imgsz})...")
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        project=str(here / "runs" / "train"),
        name=args.name,
        # ultralytics 8.4.x rejects device="auto" here even when CUDA is free;
        # pick the first GPU, fall back to cpu if none.
        device="0" if __import__("torch").cuda.is_available() else "cpu",
        # keep the best checkpoint, not just the last
        save_period=-1,
        patience=20,           # early stop if no val improvement
        cos_lr=True,
        augment=True,          # hsv, flip, scale -- helps generalise to varied CCTV
        fliplr=0.0,            # do NOT flip horizontally: traffic flows are directional
        mixup=0.0,
    )

    # Evaluate the best epoch on the val split -> real mAP/prec/recall
    best = Path(here / "runs" / "train" / args.name / "weights" / "best.pt")
    if best.exists():
        print(f"\nValidating best weights: {best}")
        model_best = YOLO(str(best))
        metrics = model_best.val(data=str(data_yaml), split="val", verbose=False)
        print(f"  mAP50    = {metrics.box.map50:.4f}")
        print(f"  mAP50-95 = {metrics.box.map:.4f}")
        print(f"  precision= {metrics.box.mp:.4f}")
        print(f"  recall   = {metrics.box.mr:.4f}")
    print(f"\nDone. Best model: {best if best.exists() else '(not found)'}")


if __name__ == "__main__":
    main()
