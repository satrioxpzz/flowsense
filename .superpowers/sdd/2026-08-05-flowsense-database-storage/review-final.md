445a174 feat: add density field to Detection schema
f4d29eb feat: wire RecordSink and SnapshotSink into runner
5757a2a feat: add S3SnapshotSink for Garage/disk storage
77a1b49 feat: add PostgresSink for database ingestion
02d17ee feat: add psycopg and Sink interfaces
 flowsense/api_server/schemas.py |   1 +
 flowsense/config.py             |  11 ++++
 flowsense/database/models.py    |   1 +
 flowsense/runner.py             |  99 +++++++++++++++++++++--------------
 flowsense/sink.py               |  71 +++++++++++++++++++++++++
 requirements.txt                |  30 ++++++-----
 tests/test_config.py            |  11 ++++
 tests/test_database_schema.py   |  51 ++++++++++++++++++
 tests/test_runner.py            |  48 +++++++++++++++++
 tests/test_sink.py              | 112 ++++++++++++++++++++++++++++++++++++++++
 10 files changed, 382 insertions(+), 53 deletions(-)
diff --git a/flowsense/api_server/schemas.py b/flowsense/api_server/schemas.py
index d4b4abf..db50b1a 100644
--- a/flowsense/api_server/schemas.py
+++ b/flowsense/api_server/schemas.py
@@ -17,20 +17,21 @@ class CameraResponse(CameraBase):
     created_at: datetime
     updated_at: datetime
     model_config = ConfigDict(from_attributes=True)
 
 class DetectionBase(BaseModel):
     camera_id: int
     timestamp: datetime
     total_vehicles: int
     per_lane: Dict[str, Any]
     crossings: Dict[str, Any]
+    density: Optional[Dict[str, Any]] = None
 
 class DetectionCreate(DetectionBase):
     pass
 
 class DetectionResponse(DetectionBase):
     id: int
     model_config = ConfigDict(from_attributes=True)
 
 class IntersectionBase(BaseModel):
     name: str
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
diff --git a/flowsense/database/models.py b/flowsense/database/models.py
index 1b2143b..b11f0cc 100644
--- a/flowsense/database/models.py
+++ b/flowsense/database/models.py
@@ -18,20 +18,21 @@ class Camera(Base):
     detections = relationship("Detection", back_populates="camera")
 
 class Detection(Base):
     __tablename__ = "detections"
     id = Column(Integer, primary_key=True, index=True)
     camera_id = Column(Integer, ForeignKey("cameras.id"))
     timestamp = Column(DateTime, default=datetime.utcnow, index=True)
     total_vehicles = Column(Integer, default=0)
     per_lane = Column(JSON)
     crossings = Column(JSON)
+    density = Column(JSON)
     camera = relationship("Camera", back_populates="detections")
 
 class Intersection(Base):
     __tablename__ = "intersections"
     id = Column(Integer, primary_key=True, index=True)
     name = Column(String, index=True)
     location_lat = Column(Float)
     location_lng = Column(Float)
     location = Column(Geometry('POINT'))
     signal_config = Column(JSON)
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
diff --git a/flowsense/sink.py b/flowsense/sink.py
new file mode 100644
index 0000000..14615bc
--- /dev/null
+++ b/flowsense/sink.py
@@ -0,0 +1,71 @@
+import json
+from pathlib import Path
+
+class RecordSink:
+    def emit(self, record: dict):
+        raise NotImplementedError
+
+class JsonlSink(RecordSink):
+    def __init__(self, filepath):
+        self.filepath = Path(filepath)
+        self.filepath.parent.mkdir(parents=True, exist_ok=True)
+
+    def emit(self, record: dict):
+        with open(self.filepath, "a", encoding="utf-8") as f:
+            f.write(json.dumps(record, separators=(",", ":")) + "\n")
+            f.flush()
+
+class SnapshotSink:
+    def save(self, camera_id: str, ts: float, frame_bytes: bytes):
+        raise NotImplementedError
+
+
+class PostgresSink(RecordSink):
+    def __init__(self, conn_str: str):
+        self.conn_str = conn_str
+
+    def emit(self, record: dict):
+        import psycopg
+        from datetime import datetime, timezone
+
+        with psycopg.connect(self.conn_str) as conn:
+            with conn.cursor() as cur:
+                ts = datetime.fromtimestamp(record["ts"], tz=timezone.utc)
+                cur.execute(
+                    "INSERT INTO detections (camera_id, timestamp, total_vehicles, per_lane, crossings, density) "
+                    "VALUES (%s, %s, %s, %s, %s, %s)",
+                    (
+                        record["camera_id"],
+                        ts,
+                        record["total_vehicles"],
+                        json.dumps(record.get("per_lane", {})),
+                        json.dumps(record.get("crossings", {})),
+                        json.dumps(record.get("density", {})),
+                    ),
+                )
+            conn.commit()
+
+
+class S3SnapshotSink(SnapshotSink):
+    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str):
+        import boto3
+
+        self.bucket = bucket
+        self.client = boto3.client(
+            "s3",
+            endpoint_url=endpoint_url,
+            aws_access_key_id=access_key,
+            aws_secret_access_key=secret_key,
+            region_name="us-east-1",
+        )
+
+    def save(self, camera_id: str, ts: float, frame_bytes: bytes):
+        key = f"snapshots/{camera_id}/{camera_id}_{int(ts)}.jpg"
+        self.client.put_object(
+            Bucket=self.bucket,
+            Key=key,
+            Body=frame_bytes,
+            ContentType="image/jpeg",
+        )
+
+
diff --git a/requirements.txt b/requirements.txt
index cafaa4d..2dba6ed 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,14 +1,16 @@
-ultralytics
-opencv-python
-numpy
-requests
-boto3
-fastapi
-uvicorn[standard]
-sqlalchemy[asyncio]
-asyncpg
-alembic
-pydantic
-python-jose[cryptography]
-passlib[bcrypt]
-geoalchemy2
+ultralytics==8.2.88
+opencv-python==4.10.0.84
+numpy==1.26.4
+requests==2.32.3
+boto3==1.34.109
+fastapi==0.111.0
+uvicorn[standard]==0.30.1
+sqlalchemy[asyncio]==2.0.30
+asyncpg==0.29.0
+alembic==1.13.1
+pydantic==2.7.4
+python-jose[cryptography]==3.3.0
+passlib[bcrypt]==1.7.4
+geoalchemy2==0.14.2
+aiofiles==24.1.0
+psycopg[binary]==3.1.18
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
diff --git a/tests/test_database_schema.py b/tests/test_database_schema.py
new file mode 100644
index 0000000..4e44ec4
--- /dev/null
+++ b/tests/test_database_schema.py
@@ -0,0 +1,51 @@
+from datetime import datetime, timezone
+from flowsense.database.models import Detection
+from flowsense.api_server.schemas import DetectionBase, DetectionCreate, DetectionResponse
+
+
+def test_detection_model_density_column():
+    assert hasattr(Detection, "density")
+    detection = Detection(
+        camera_id=1,
+        total_vehicles=10,
+        per_lane={"lane1": 5},
+        crossings={},
+        density={"level": "HIGH", "score": 0.85},
+    )
+    assert detection.density == {"level": "HIGH", "score": 0.85}
+
+
+def test_detection_schema_density_optional():
+    now = datetime.now(timezone.utc)
+    # Test default None
+    det_base = DetectionBase(
+        camera_id=1,
+        timestamp=now,
+        total_vehicles=5,
+        per_lane={},
+        crossings={},
+    )
+    assert det_base.density is None
+
+    # Test with density dict provided
+    det_create = DetectionCreate(
+        camera_id=1,
+        timestamp=now,
+        total_vehicles=5,
+        per_lane={},
+        crossings={},
+        density={"level": "LOW", "score": 0.2},
+    )
+    assert det_create.density == {"level": "LOW", "score": 0.2}
+
+    det_resp = DetectionResponse(
+        id=42,
+        camera_id=1,
+        timestamp=now,
+        total_vehicles=5,
+        per_lane={},
+        crossings={},
+        density={"level": "MEDIUM", "score": 0.5},
+    )
+    assert det_resp.id == 42
+    assert det_resp.density == {"level": "MEDIUM", "score": 0.5}
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
diff --git a/tests/test_sink.py b/tests/test_sink.py
new file mode 100644
index 0000000..0cc13e2
--- /dev/null
+++ b/tests/test_sink.py
@@ -0,0 +1,112 @@
+import json
+from flowsense.sink import JsonlSink
+
+def test_jsonl_sink_emits(tmp_path):
+    p = tmp_path / "out.jsonl"
+    sink = JsonlSink(p)
+    sink.emit({"ts": 100})
+    sink.emit({"ts": 200})
+    lines = p.read_text().splitlines()
+    assert json.loads(lines[0]) == {"ts": 100}
+    assert json.loads(lines[1]) == {"ts": 200}
+
+
+class FakeCursor:
+    def __init__(self):
+        self.execs = []
+
+    def execute(self, query, params):
+        self.execs.append((query, params))
+
+
+class FakeCursorContext(FakeCursor):
+    def __enter__(self):
+        return self
+
+    def __exit__(self, exc_type, exc_value, traceback):
+        pass
+
+
+class FakeConnection:
+    def __init__(self):
+        self.cursor_obj = FakeCursorContext()
+        self.committed = False
+
+    def cursor(self):
+        return self.cursor_obj
+
+    def __enter__(self):
+        return self
+
+    def __exit__(self, exc_type, exc_value, traceback):
+        pass
+
+    def commit(self):
+        self.committed = True
+
+
+def test_postgres_sink(monkeypatch):
+    import sys
+    import types
+
+    if "psycopg" not in sys.modules or sys.modules["psycopg"] is None:
+        dummy_psycopg = types.ModuleType("psycopg")
+        sys.modules["psycopg"] = dummy_psycopg
+
+    import psycopg
+    from flowsense.sink import PostgresSink
+
+    conn = FakeConnection()
+    monkeypatch.setattr(psycopg, "connect", lambda url: conn, raising=False)
+
+
+    sink = PostgresSink("fake_url")
+    sink.emit({
+        "ts": 100,
+        "camera_id": 30,
+        "total_vehicles": 2,
+        "per_lane": {},
+        "crossings": {},
+        "density": {},
+    })
+
+    q, p = conn.cursor().execs[0]
+    assert "INSERT INTO detections" in q
+    assert p[0] == 30  # camera_id
+    assert p[2] == 2  # total_vehicles
+    assert conn.committed
+
+
+class FakeS3Client:
+    def __init__(self):
+        self.uploads = []
+
+    def put_object(self, Bucket, Key, Body, ContentType):
+        self.uploads.append((Bucket, Key, Body, ContentType))
+
+
+def test_s3_snapshot_sink(monkeypatch):
+    import sys
+    import types
+
+    if "boto3" not in sys.modules or sys.modules["boto3"] is None:
+        dummy_boto3 = types.ModuleType("boto3")
+        sys.modules["boto3"] = dummy_boto3
+
+    import boto3
+    from flowsense.sink import S3SnapshotSink
+
+    client = FakeS3Client()
+    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client, raising=False)
+
+    sink = S3SnapshotSink(endpoint_url="http://x", access_key="a", secret_key="b", bucket="snaps")
+    sink.save("cam1", 100.5, b"img")
+
+    assert len(client.uploads) == 1
+    bucket, key, body, ctype = client.uploads[0]
+    assert bucket == "snaps"
+    assert "cam1_100" in key
+    assert body == b"img"
+    assert ctype == "image/jpeg"
+
+
