"""
FlowSense ROI calibrator - draw per-lane polygons on a CCTV frame.

Click vertices of a polygon around each lane's stop area, press 'n' to
accept and move to the next lane, 'u' to undo last vertex, 'q' to save.

Usage:
    python calibrate.py --camera-id 30 --lanes "L1,L2,L3,L4"
    python calibrate.py --url <m3u8 url> --lanes "kota,ploso,demak,sekoe"
"""

import argparse
import json
import os
import sys
from pathlib import Path

import cv2

from flowsense.config import load_config
from flowsense.cctv_client import fetch_cameras

BASE_DIR = Path(__file__).resolve().parent
ROIS_PATH = BASE_DIR / "config" / "rois.json"

_CONFIG = load_config()
API_URL = _CONFIG.api_url
API_KEY = _CONFIG.api_key


def load_camera(cam_id=None, url=None):
    if url:
        return {"id": "custom", "nama": "custom", "url": url}
    cameras = fetch_cameras(_CONFIG)
    for c in cameras:
        if str(c["id"]) == str(cam_id):
            return c
    raise RuntimeError(f"No camera with id={cam_id}")


def grab_frame(cam):
    cap = cv2.VideoCapture(cam["url"])
    frame = None
    for _ in range(30):  # skip warmup frames
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
    cap.release()
    if frame is None:
        raise RuntimeError("Could not grab a frame from the stream")
    return frame


def main():
    ap = argparse.ArgumentParser(description="FlowSense ROI calibrator")
    ap.add_argument("--camera-id", help="camera id from the API")
    ap.add_argument("--url", help="direct m3u8 url")
    ap.add_argument("--lanes", required=True,
                    help="comma-separated lane names in draw order")
    ap.add_argument("--out", help="output json file (default: config/rois.json)")
    args = ap.parse_args()

    if not API_KEY:
        raise SystemExit(
            "FLOWSENSE_API_KEY is not set; copy .env.example to .env and fill it in"
        )

    cam = load_camera(cam_id=args.camera_id, url=args.url)
    camera_key = str(cam["id"])
    lane_names = [x.strip() for x in args.lanes.split(",")]
    print(f"[calibrate] camera {camera_key} '{cam.get('nama')}' lanes={lane_names}")

    frame = grab_frame(cam)
    h, w = frame.shape[:2]
    scale = min(1.0, 1400.0 / w)
    if scale < 1.0:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    print(f"[calibrate] frame {w}x{h} (display {frame.shape[1]}x{frame.shape[0]})")
    print("[calibrate] left-click = add vertex, 'n' = next lane, "
          "'u' = undo, 'q' = save & quit")

    rois = {}
    if ROIS_PATH.exists():
        rois = json.loads(ROIS_PATH.read_text(encoding="utf-8"))
    rois.setdefault(camera_key, {})

    import numpy as np

    current = 0
    points = []
    display = frame.copy()

    def redraw():
        nonlocal display
        display = frame.copy()
        for i, name in enumerate(lane_names):
            if i < current and name in rois[camera_key]:
                poly = np.array(rois[camera_key][name], np.int32).reshape(-1, 1, 2)
                cv2.polylines(display, [poly], True, (0, 255, 0), 2)
        if points:
            pts = np.array(points, np.int32).reshape(-1, 1, 2)
            cv2.polylines(display, [pts], False, (0, 0, 255), 2)
            for p in points:
                cv2.circle(display, tuple(p), 4, (0, 0, 255), -1)
        cv2.putText(display, f"lane[{current}] {lane_names[current]} - {len(points)} pts "
                    f"(n=next u=undo q=save)",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        cv2.imshow("calibrate", display)

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
            print(f"[calibrate] vertex ({x},{y})")
            redraw()

    cv2.namedWindow("calibrate")
    cv2.setMouseCallback("calibrate", on_click)
    redraw()
    while True:
        k = cv2.waitKey(20) & 0xFF
        if k == ord("n"):
            if len(points) >= 3:
                if scale < 1.0:
                    points = [[int(x / scale) for x in p] for p in points]
                rois[camera_key][lane_names[current]] = points
                points = []
                current += 1
                if current >= len(lane_names):
                    break
            else:
                print("[calibrate] need at least 3 points for this lane")
        elif k == ord("u"):
            if points:
                points.pop()
        elif k == ord("q"):
            if len(points) >= 3 and current < len(lane_names):
                if scale < 1.0:
                    points = [[int(x / scale) for x in p] for p in points]
                rois[camera_key][lane_names[current]] = points
                points = []
                current += 1
            # Save original resolution
            rois[camera_key]["_resolution"] = [w, h]
            break

        redraw()

    cv2.destroyAllWindows()

    out_path = args.out or str(ROIS_PATH)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(rois, indent=2), encoding="utf-8")
    print(f"[calibrate] saved {sum(len(v) for v in rois[camera_key].values())} lanes "
          f"for camera {camera_key} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
