"""FlowSense runner: main loop, CLI, graceful shutdown."""
import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from .api import fetch_cameras, find_camera
from .config import load_config
from .counter import TrackingCounter
from .density import classify_density
from .detector import load_model, summarize_frame, track_summary, pedestrian_detections
from .lanes import load_rois
from .sink import JsonlSink, PostgresSink, S3SnapshotSink
from .stream import ReconnectingStream
from .telemetry import setup_logging

log = logging.getLogger("flowsense")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="FlowSense edge connector")
    ap.add_argument("--camera", help="camera name substring, e.g. 'Simpang DPRD Arah Kota'")
    ap.add_argument("--camera-id", help="camera id from the API")
    ap.add_argument("--url", help="direct m3u8 url (bypasses the camera API)")
    ap.add_argument("--out", help="output .jsonl file")
    ap.add_argument("--model", help="yolo weights path (default: config FLOWSENSE_MODEL)")
    ap.add_argument("--interval", type=float, help="seconds between records (default: config)")
    ap.add_argument("--sink", default="jsonl", help="comma-separated sinks to emit records to: jsonl, postgres")
    ap.add_argument("--snapshot", action="store_true", help="save snapshot frames to S3 sink")
    ap.add_argument("--track", action="store_true",
                    help="use YOLO tracking to count unique lane crossings")
    ap.add_argument("--vision", action="store_true",
                    help="occasionally classify pedestrian crops via local Qwen (ollama) "
                         "for mobility-aid needs; requires Ollama running")
    ap.add_argument("--vision-interval", type=float, default=None,
                    help="seconds cooldown before re-classifying the same pedestrian "
                         "(default: config FLOWSENSE_VISION_INTERVAL)")
    ap.add_argument("--snapshot-only", action="store_true",
                    help="detect on one frame then exit (used for calibration)")
    ap.add_argument("--show", action="store_true", help="display annotated frames")
    ap.add_argument("--skip-detect", action="store_true",
                    help="just read frames (test stream before installing model)")
    ap.add_argument("--log-json", action="store_true", default=True,
                    help="structured JSON logs (default)")
    ap.add_argument("--log-level", default="INFO")
    return ap.parse_args(argv)


def build_record(ts, camera, summary, crossings=None, density=None, pedestrians=None):
    record = {
        "ts": int(ts),
        "camera_id": camera["id"],
        "camera": camera.get("nama", ""),
        "total_vehicles": summary.get("total_vehicles", 0),
        "per_lane": summary.get("per_lane", {}),
    }
    if crossings is not None:
        record["crossings"] = crossings
    if density is not None:
        record["density"] = density
    if pedestrians is not None:
        record["pedestrians"] = len(pedestrians)
        record["vision"] = [
            {
                "track_id": p.get("track_id"),
                "has_mobility_aid": (p.get("vision") or {}).get("has_mobility_aid"),
                "aid_type": (p.get("vision") or {}).get("aid_type"),
            }
            for p in pedestrians
            if p.get("vision")
        ]
    return record


def per_lane_present(dets):
    counts = {}
    for d in dets:
        if d.get("lane"):
            counts[d["lane"]] = counts.get(d["lane"], 0) + 1
    return counts


def annotate(frame, lanes, summary):
    for name, poly in lanes.items():
        pts = np.array(poly, np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
        cx = int(np.mean([p[0] for p in poly]))
        cy = int(np.mean([p[1] for p in poly]))
        cv2.putText(frame, f"{name}: {summary['per_lane'].get(name, 0)}",
                    (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return frame


def crop_bbox(frame, bbox, pad: int = 10):
    """Crop a YOLO xyxy bbox out of a frame with padding, clamped to bounds."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2]


class VisionClassifier:
    """Throttled wrapper around ollama_vision.detect_accessibility_needs.

    Classifies each pedestrian crop at most once per cooldown window (per
    track id, or per quantized bbox when tracking is off), reusing cached
    results the rest of the time so Qwen's slow inference stays off the
    real-time path.
    """

    def __init__(self, crops_dir, cooldown: float = 30.0):
        self.crops_dir = Path(crops_dir)
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        self.cooldown = cooldown
        self._cache = {}

    @staticmethod
    def _key(det) -> str:
        tid = det.get("track_id")
        if tid is not None:
            return f"t{tid}"
        x1, y1, x2, y2 = [int(v // 10) for v in det["bbox"]]
        return f"b{x1}_{y1}_{x2}_{y2}"

    def classify(self, det, frame, now: float) -> dict:
        key = self._key(det)
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.cooldown:
            return cached[1]
        crop = crop_bbox(frame, det["bbox"])
        if crop is None:
            return {"has_mobility_aid": None, "aid_type": "unclear",
                    "notes": "invalid bbox crop"}
        fname = f"pedestrian_{key}_{int(now)}.jpg"
        fpath = self.crops_dir / fname
        cv2.imwrite(str(fpath), crop)
        from .ollama_vision import detect_accessibility_needs
        result = detect_accessibility_needs(str(fpath))
        self._cache[key] = (now, result)
        return result


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = load_config()
    if args.interval is not None:
        cfg = replace(cfg, interval=args.interval)
    if args.model:
        cfg = replace(cfg, model_path=args.model)

    setup_logging(args.log_level, args.log_json)
    if not cfg.api_key:
        log.warning("FLOWSENSE_API_KEY is not set; copy .env.example to .env")

    if args.url:
        cam = {"id": "custom", "nama": "custom", "url": args.url}
    else:
        cameras = fetch_cameras(cfg)
        cam = find_camera(cameras, name=args.camera, cam_id=args.camera_id)
    camera_key = str(cam["id"])
    log.info("camera", extra={"camera_id": camera_key, "camera": cam.get("nama", "")})
    log.info("stream", extra={"url": cam["url"]})

    lanes = load_rois(cfg.rois_path, camera_key)
    if not lanes:
        log.warning("no lane ROIs for camera %s; run: python calibrate.py --camera-id %s",
                    camera_key, camera_key)

    model = None
    if not args.skip_detect:
        model = load_model(cfg.model_path)
        log.info("model loaded", extra={"model": cfg.model_path})

    vision = None
    if args.vision:
        if args.skip_detect:
            log.warning("--vision requires the detection model; ignoring")
        else:
            vision_interval = args.vision_interval if args.vision_interval is not None else cfg.vision_interval
            vision = VisionClassifier(cfg.data_dir / "crops", vision_interval)
            log.info("vision enabled", extra={"cooldown_s": vision_interval, "model": "qwen3.5:9b-q4_K_M"})

    stream = ReconnectingStream(cam["url"])
    stream.open()
    out_path = Path(args.out) if args.out else cfg.data_dir / f"connector_{camera_key}.jsonl"

    record_sinks = []
    if "jsonl" in args.sink:
        record_sinks.append(JsonlSink(out_path))
    if "postgres" in args.sink:
        if cfg.db_url:
            record_sinks.append(PostgresSink(cfg.db_url))
        else:
            log.warning("postgres sink requested but db_url configuration is missing")

    snap_sink = None
    if getattr(args, 'snapshot', False):
        if cfg.s3_endpoint:
            snap_sink = S3SnapshotSink(cfg.s3_endpoint, cfg.s3_access_key, cfg.s3_secret_key, cfg.s3_bucket)
        else:
            log.warning("snapshot sink requested but s3_endpoint configuration is missing")

    counter = TrackingCounter() if args.track else None
    last_emit = 0.0
    try:
        while True:
            ok, frame = stream.read()
            if not ok:
                log.error("stream lost after reconnects; giving up")
                break

            now = time.time()
            summary = {}
            crossings = None
            if model is not None:
                if args.track:
                    results = model.track(frame, persist=True, verbose=False)
                    dets, pairs = track_summary(results, lanes, cfg.min_conf)
                    summary = {
                        "total_vehicles": len(dets),
                        "per_lane": per_lane_present(dets),
                        "vehicles": dets,
                    }
                    crossings = counter.update(pairs)
                else:
                    results = model(frame, verbose=False)
                    summary = summarize_frame(results, lanes, cfg.min_conf)

                if vision is not None:
                    ped_dets = pedestrian_detections(results, lanes, cfg.min_conf)
                    for d in ped_dets:
                        d["vision"] = vision.classify(d, frame, now)
                    summary["pedestrians"] = ped_dets

            if now - last_emit >= cfg.interval:
                density = classify_density(summary.get("per_lane", {}))
                record = build_record(now, cam, summary, crossings, density,
                                      pedestrians=summary.get("pedestrians"))
                for sink in record_sinks:
                    try:
                        sink.emit(record)
                    except Exception as e:
                        log.error("sink error", exc_info=True)
                if snap_sink:
                    ok_enc, buf = cv2.imencode('.jpg', frame)
                    if ok_enc:
                        try:
                            snap_sink.save(camera_key, now, buf.tobytes())
                        except Exception as e:
                            log.error("snap error", exc_info=True)
                last_emit = now
                log.info("record", extra={"camera_id": camera_key, "event": json.dumps(record)})

            if args.show and model is not None:
                view = annotate(frame.copy(), lanes, summary)
                cv2.imshow("flowsense", view)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if args.snapshot_only:
                break
    except KeyboardInterrupt:
        log.info("interrupted; shutting down")
    finally:
        stream.release()
        log.info("done", extra={"event": f"metadata -> {out_path}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
