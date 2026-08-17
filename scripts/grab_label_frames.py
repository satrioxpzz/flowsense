"""Grab raw frames for CVAT labeling (Step 1 of the fine-tune pipeline).

This collects unlabeled frames from live Kudus cams into
data/cvat_dataset/raw/ so a human can upload them to CVAT, draw boxes, and
export YOLO-format labels back into data/cvat_dataset/labels/.

It deliberately does NOT auto-label (that would lock in base-model errors --
see AUDIT P2-4). The frames are raw material only.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

from flowsense.config import load_config
from flowsense.cctv_client import fetch_cameras
from flowsense.stream import ReconnectingStream


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grab raw frames for CVAT labeling")
    ap.add_argument("--out-dir", default="data/cvat_dataset/raw")
    ap.add_argument("--cameras", nargs="*", default=None,
                    help="camera name substrings; default = first N")
    ap.add_argument("--limit", type=int, default=5, help="frames per camera")
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between grabs")
    ap.add_argument("--max-cameras", type=int, default=4)
    args = ap.parse_args(argv)

    cfg = load_config()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cams = fetch_cameras(cfg)
    if args.cameras:
        picked = []
        for sub in args.cameras:
            for c in cams:
                if sub.lower() in (c.get("nama") or "").lower():
                    picked.append(c)
        cams = picked
    cams = cams[: args.max_cameras]

    if not cams:
        print("No cameras matched.")
        return 2

    for cam in cams:
        name = (cam.get("nama") or f"cam{cam.get('id')}").replace(" ", "_")
        url = cam.get("url")
        if not url:
            continue
        print(f"Capturing {args.limit} frames from {name}...")
        stream = ReconnectingStream(url)
        try:
            stream.open()
        except RuntimeError:
            print(f"  failed to open {name}, skipping")
            continue
        got = 0
        while got < args.limit:
            ok, frame = stream.read()
            if not ok:
                break
            ts = int(time.time() * 1000)
            cv2.imwrite(str(out_dir / f"{name}_{ts}_{got}.jpg"), frame)
            got += 1
            print(f"  {got}/{args.limit}")
            if got < args.limit:
                time.sleep(args.interval)
        stream.release()
    print(f"\nFrames -> {out_dir}")
    print("Next: upload to CVAT, annotate vehicle classes, export YOLO format")
    print("into data/cvat_dataset/labels/{train,val}, then run train_yolo.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
