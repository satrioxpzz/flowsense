f4d29eb feat: wire RecordSink and SnapshotSink into runner
 flowsense/config.py  | 11 ++++++
 flowsense/runner.py  | 99 +++++++++++++++++++++++++++++++---------------------
 tests/test_config.py | 11 ++++++
 tests/test_runner.py | 48 +++++++++++++++++++++++++
 4 files changed, 130 insertions(+), 39 deletions(-)
diff --git a/flowsense/config.py b/flowsense/config.py
index d90649f..47bd292 100644
--- a/flowsense/config.py
+++ b/flowsense/config.py
@@ -21,20 +21,25 @@ def _load_dotenv(path: Path) -> None:
 @dataclass(frozen=True)
 class Config:
     api_url: str = "https://kudussehat.kuduskab.go.id/api/get-cctv"
     api_key: str = ""
     api_timeout: float = 25.0
     api_retries: int = 3
     api_backoff: float = 2.0
     min_conf: float = 0.35
     interval: float = 2.0
     model_path: str = "yolo11n.pt"
+    db_url: str = ""
+    s3_endpoint: str = ""
+    s3_access_key: str = ""
+    s3_secret_key: str = ""
+    s3_bucket: str = ""
     base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
 
     @property
     def rois_path(self) -> Path:
         return self.base_dir / "config" / "rois.json"
 
     @property
     def data_dir(self) -> Path:
         return self.base_dir / "data"
 
@@ -44,11 +49,17 @@ def load_config(env_path: Path = DEFAULT_ENV_PATH) -> Config:
     defaults = Config()
     return Config(
         api_url=os.environ.get("FLOWSENSE_API_URL", defaults.api_url),
         api_key=os.environ.get("FLOWSENSE_API_KEY", defaults.api_key),
         api_timeout=float(os.environ.get("FLOWSENSE_API_TIMEOUT", defaults.api_timeout)),
         api_retries=int(os.environ.get("FLOWSENSE_API_RETRIES", defaults.api_retries)),
         api_backoff=float(os.environ.get("FLOWSENSE_API_BACKOFF", defaults.api_backoff)),
         min_conf=float(os.environ.get("FLOWSENSE_MIN_CONF", defaults.min_conf)),
         interval=float(os.environ.get("FLOWSENSE_INTERVAL", defaults.interval)),
         model_path=os.environ.get("FLOWSENSE_MODEL", defaults.model_path),
+        db_url=os.environ.get("FLOWSENSE_DB_URL", defaults.db_url),
+        s3_endpoint=os.environ.get("FLOWSENSE_S3_ENDPOINT", defaults.s3_endpoint),
+        s3_access_key=os.environ.get("FLOWSENSE_S3_ACCESS_KEY", defaults.s3_access_key),
+        s3_secret_key=os.environ.get("FLOWSENSE_S3_SECRET_KEY", defaults.s3_secret_key),
+        s3_bucket=os.environ.get("FLOWSENSE_S3_BUCKET", defaults.s3_bucket),
     )
+
diff --git a/flowsense/runner.py b/flowsense/runner.py
index 2695df0..6dff38e 100644
--- a/flowsense/runner.py
+++ b/flowsense/runner.py
@@ -9,34 +9,37 @@ from pathlib import Path
 
 import cv2
 import numpy as np
 
 from .api import fetch_cameras, find_camera
 from .config import load_config
 from .counter import TrackingCounter
 from .density import classify_density
 from .detector import load_model, summarize_frame, track_summary
 from .lanes import load_rois
+from .sink import JsonlSink, PostgresSink, S3SnapshotSink
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
+    ap.add_argument("--sink", default="jsonl", help="comma-separated sinks to emit records to: jsonl, postgres")
+    ap.add_argument("--snapshot", action="store_true", help="save snapshot frames to S3 sink")
     ap.add_argument("--track", action="store_true",
                     help="use YOLO tracking to count unique lane crossings")
     ap.add_argument("--snapshot-only", action="store_true",
                     help="detect on one frame then exit (used for calibration)")
     ap.add_argument("--show", action="store_true", help="display annotated frames")
     ap.add_argument("--skip-detect", action="store_true",
                     help="just read frames (test stream before installing model)")
     ap.add_argument("--log-json", action="store_true", default=True,
                     help="structured JSON logs (default)")
     ap.add_argument("--log-level", default="INFO")
@@ -104,65 +107,83 @@ def main(argv=None) -> int:
                     camera_key, camera_key)
 
     model = None
     if not args.skip_detect:
         model = load_model(cfg.model_path)
         log.info("model loaded", extra={"model": cfg.model_path})
 
     stream = ReconnectingStream(cam["url"])
     stream.open()
     out_path = Path(args.out) if args.out else cfg.data_dir / f"connector_{camera_key}.jsonl"
-    out_path.parent.mkdir(parents=True, exist_ok=True)
+
+    record_sinks = []
+    if "jsonl" in args.sink:
+        record_sinks.append(JsonlSink(out_path))
+    if "postgres" in args.sink and cfg.db_url:
+        record_sinks.append(PostgresSink(cfg.db_url))
+
+    snap_sink = None
+    if getattr(args, 'snapshot', False) and cfg.s3_endpoint:
+        snap_sink = S3SnapshotSink(cfg.s3_endpoint, cfg.s3_access_key, cfg.s3_secret_key, cfg.s3_bucket)
 
     counter = TrackingCounter() if args.track else None
     last_emit = 0.0
     try:
-        with open(out_path, "a", encoding="utf-8") as f:
-            while True:
-                ok, frame = stream.read()
-                if not ok:
-                    log.error("stream lost after reconnects; giving up")
+        while True:
+            ok, frame = stream.read()
+            if not ok:
+                log.error("stream lost after reconnects; giving up")
+                break
+
+            now = time.time()
+            summary = {}
+            crossings = None
+            if model is not None:
+                if args.track:
+                    results = model.track(frame, persist=True, verbose=False)
+                    dets, pairs = track_summary(results, lanes, cfg.min_conf)
+                    summary = {
+                        "total_vehicles": len(dets),
+                        "per_lane": per_lane_present(dets),
+                        "vehicles": dets,
+                    }
+                    crossings = counter.update(pairs)
+                else:
+                    results = model(frame, verbose=False)
+                    summary = summarize_frame(results, lanes, cfg.min_conf)
+
+            if now - last_emit >= cfg.interval:
+                density = classify_density(summary.get("per_lane", {}))
+                record = build_record(now, cam, summary, crossings, density)
+                for sink in record_sinks:
+                    try:
+                        sink.emit(record)
+                    except Exception as e:
+                        log.error("sink error", exc_info=True)
+                if snap_sink:
+                    ok_enc, buf = cv2.imencode('.jpg', frame)
+                    if ok_enc:
+                        try:
+                            snap_sink.save(camera_key, now, buf.tobytes())
+                        except Exception as e:
+                            log.error("snap error", exc_info=True)
+                last_emit = now
+                log.info("record", extra={"camera_id": camera_key, "event": json.dumps(record)})
+
+            if args.show and model is not None:
+                view = annotate(frame.copy(), lanes, summary)
+                cv2.imshow("flowsense", view)
+                if cv2.waitKey(1) & 0xFF == ord("q"):
                     break
 
-                now = time.time()
-                summary = {}
-                crossings = None
-                if model is not None:
-                    if args.track:
-                        results = model.track(frame, persist=True, verbose=False)
-                        dets, pairs = track_summary(results, lanes, cfg.min_conf)
-                        summary = {
-                            "total_vehicles": len(dets),
-                            "per_lane": per_lane_present(dets),
-                            "vehicles": dets,
-                        }
-                        crossings = counter.update(pairs)
-                    else:
-                        results = model(frame, verbose=False)
-                        summary = summarize_frame(results, lanes, cfg.min_conf)
-
-                if now - last_emit >= cfg.interval:
-                    density = classify_density(summary.get("per_lane", {}))
-                    record = build_record(now, cam, summary, crossings, density)
-                    f.write(json.dumps(record, separators=(",", ":")) + "\n")
-                    f.flush()
-                    last_emit = now
-                    log.info("record", extra={"camera_id": camera_key, "event": json.dumps(record)})
-
-                if args.show and model is not None:
-                    view = annotate(frame.copy(), lanes, summary)
-                    cv2.imshow("flowsense", view)
-                    if cv2.waitKey(1) & 0xFF == ord("q"):
-                        break
-
-                if args.snapshot_only:
-                    break
+            if args.snapshot_only:
+                break
     except KeyboardInterrupt:
         log.info("interrupted; shutting down")
     finally:
         stream.release()
         log.info("done", extra={"event": f"metadata -> {out_path}"})
     return 0
 
 
 if __name__ == "__main__":
     sys.exit(main())
diff --git a/tests/test_config.py b/tests/test_config.py
index 02ec495..8a7775a 100644
--- a/tests/test_config.py
+++ b/tests/test_config.py
@@ -31,10 +31,21 @@ def test_dotenv_loaded_when_env_unset(tmp_path, monkeypatch):
     assert cfg.api_key == "dot-secret"
     assert cfg.interval == 7.0
 
 
 def test_env_beats_dotenv(tmp_path, monkeypatch):
     env = tmp_path / ".env"
     env.write_text('FLOWSENSE_API_KEY=dot-secret\n', encoding="utf-8")
     monkeypatch.setenv("FLOWSENSE_API_KEY", "real-secret")
     cfg = load_config(env_path=env)
     assert cfg.api_key == "real-secret"
+
+
+def test_db_s3_config_defaults(tmp_path):
+    from flowsense.config import load_config
+    cfg = load_config(env_path=tmp_path / "missing.env")
+    assert cfg.db_url == ""
+    assert cfg.s3_endpoint == ""
+    assert cfg.s3_access_key == ""
+    assert cfg.s3_secret_key == ""
+    assert cfg.s3_bucket == ""
+
diff --git a/tests/test_runner.py b/tests/test_runner.py
index 2ddce41..37ec7f1 100644
--- a/tests/test_runner.py
+++ b/tests/test_runner.py
@@ -46,10 +46,58 @@ def test_parse_args_keeps_legacy_flags():
 
 
 def test_build_record_with_density():
     r = build_record(
         100.0,
         CAMERA,
         {"total_vehicles": 0, "per_lane": {}, "vehicles": []},
         density={"kota": "sedang"}
     )
     assert r["density"] == {"kota": "sedang"}
+
+
+def test_parse_args_sink_and_snapshot():
+    args = parse_args(["--sink", "jsonl,postgres", "--snapshot"])
+    assert args.sink == "jsonl,postgres"
+    assert args.snapshot is True
+
+
+def test_main_with_sinks(tmp_path, monkeypatch):
+    import numpy as np
+    from unittest.mock import MagicMock, patch
+
+    out_file = tmp_path / "test_out.jsonl"
+    monkeypatch.setenv("FLOWSENSE_DB_URL", "postgresql://localhost/testdb")
+    monkeypatch.setenv("FLOWSENSE_S3_ENDPOINT", "http://localhost:9000")
+    monkeypatch.setenv("FLOWSENSE_S3_ACCESS_KEY", "access")
+    monkeypatch.setenv("FLOWSENSE_S3_SECRET_KEY", "secret")
+    monkeypatch.setenv("FLOWSENSE_S3_BUCKET", "bucket")
+
+    fake_frame = np.zeros((100, 100, 3), dtype=np.uint8)
+
+    mock_stream = MagicMock()
+    mock_stream.read.return_value = (True, fake_frame)
+
+    with patch("flowsense.runner.ReconnectingStream", return_value=mock_stream), \
+         patch("flowsense.runner.PostgresSink") as mock_pg_cls, \
+         patch("flowsense.runner.S3SnapshotSink") as mock_s3_cls:
+
+        mock_pg_instance = MagicMock()
+        mock_pg_cls.return_value = mock_pg_instance
+        mock_s3_instance = MagicMock()
+        mock_s3_cls.return_value = mock_s3_instance
+
+        from flowsense.runner import main
+        ret = main([
+            "--url", "http://fake.stream/live.m3u8",
+            "--skip-detect",
+            "--snapshot-only",
+            "--sink", "jsonl,postgres",
+            "--snapshot",
+            "--out", str(out_file),
+        ])
+
+        assert ret == 0
+        assert out_file.exists()
+        assert mock_pg_instance.emit.called
+        assert mock_s3_instance.save.called
+
