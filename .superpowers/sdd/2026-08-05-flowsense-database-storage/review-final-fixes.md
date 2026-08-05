b9a98fb fix: address final whole-branch review findings
 flowsense/runner.py                      | 14 +++++++----
 flowsense/sink.py                        | 40 +++++++++++++++-----------------
 migrations/versions/add_density_field.py | 24 +++++++++++++++++++
 tests/conftest.py                        |  7 ++++++
 tests/test_sink.py                       | 14 -----------
 5 files changed, 60 insertions(+), 39 deletions(-)
diff --git a/flowsense/runner.py b/flowsense/runner.py
index 6dff38e..9542ef9 100644
--- a/flowsense/runner.py
+++ b/flowsense/runner.py
@@ -111,26 +111,32 @@ def main(argv=None) -> int:
         model = load_model(cfg.model_path)
         log.info("model loaded", extra={"model": cfg.model_path})
 
     stream = ReconnectingStream(cam["url"])
     stream.open()
     out_path = Path(args.out) if args.out else cfg.data_dir / f"connector_{camera_key}.jsonl"
 
     record_sinks = []
     if "jsonl" in args.sink:
         record_sinks.append(JsonlSink(out_path))
-    if "postgres" in args.sink and cfg.db_url:
-        record_sinks.append(PostgresSink(cfg.db_url))
+    if "postgres" in args.sink:
+        if cfg.db_url:
+            record_sinks.append(PostgresSink(cfg.db_url))
+        else:
+            log.warning("postgres sink requested but db_url configuration is missing")
 
     snap_sink = None
-    if getattr(args, 'snapshot', False) and cfg.s3_endpoint:
-        snap_sink = S3SnapshotSink(cfg.s3_endpoint, cfg.s3_access_key, cfg.s3_secret_key, cfg.s3_bucket)
+    if getattr(args, 'snapshot', False):
+        if cfg.s3_endpoint:
+            snap_sink = S3SnapshotSink(cfg.s3_endpoint, cfg.s3_access_key, cfg.s3_secret_key, cfg.s3_bucket)
+        else:
+            log.warning("snapshot sink requested but s3_endpoint configuration is missing")
 
     counter = TrackingCounter() if args.track else None
     last_emit = 0.0
     try:
         while True:
             ok, frame = stream.read()
             if not ok:
                 log.error("stream lost after reconnects; giving up")
                 break
 
diff --git a/flowsense/sink.py b/flowsense/sink.py
index 14615bc..90685e0 100644
--- a/flowsense/sink.py
+++ b/flowsense/sink.py
@@ -1,12 +1,15 @@
 import json
 from pathlib import Path
+import psycopg
+import boto3
+from datetime import datetime, timezone
 
 class RecordSink:
     def emit(self, record: dict):
         raise NotImplementedError
 
 class JsonlSink(RecordSink):
     def __init__(self, filepath):
         self.filepath = Path(filepath)
         self.filepath.parent.mkdir(parents=True, exist_ok=True)
 
@@ -16,47 +19,42 @@ class JsonlSink(RecordSink):
             f.flush()
 
 class SnapshotSink:
     def save(self, camera_id: str, ts: float, frame_bytes: bytes):
         raise NotImplementedError
 
 
 class PostgresSink(RecordSink):
     def __init__(self, conn_str: str):
         self.conn_str = conn_str
+        self.conn = psycopg.connect(self.conn_str)
 
     def emit(self, record: dict):
-        import psycopg
-        from datetime import datetime, timezone
-
-        with psycopg.connect(self.conn_str) as conn:
-            with conn.cursor() as cur:
-                ts = datetime.fromtimestamp(record["ts"], tz=timezone.utc)
-                cur.execute(
-                    "INSERT INTO detections (camera_id, timestamp, total_vehicles, per_lane, crossings, density) "
-                    "VALUES (%s, %s, %s, %s, %s, %s)",
-                    (
-                        record["camera_id"],
-                        ts,
-                        record["total_vehicles"],
-                        json.dumps(record.get("per_lane", {})),
-                        json.dumps(record.get("crossings", {})),
-                        json.dumps(record.get("density", {})),
-                    ),
-                )
-            conn.commit()
+        with self.conn.cursor() as cur:
+            ts = datetime.fromtimestamp(record["ts"], tz=timezone.utc)
+            cur.execute(
+                "INSERT INTO detections (camera_id, timestamp, total_vehicles, per_lane, crossings, density) "
+                "VALUES (%s, %s, %s, %s, %s, %s)",
+                (
+                    record["camera_id"],
+                    ts,
+                    record["total_vehicles"],
+                    json.dumps(record.get("per_lane", {})),
+                    json.dumps(record.get("crossings", {})),
+                    json.dumps(record.get("density", {})),
+                ),
+            )
+        self.conn.commit()
 
 
 class S3SnapshotSink(SnapshotSink):
     def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str):
-        import boto3
-
         self.bucket = bucket
         self.client = boto3.client(
             "s3",
             endpoint_url=endpoint_url,
             aws_access_key_id=access_key,
             aws_secret_access_key=secret_key,
             region_name="us-east-1",
         )
 
     def save(self, camera_id: str, ts: float, frame_bytes: bytes):
diff --git a/migrations/versions/add_density_field.py b/migrations/versions/add_density_field.py
new file mode 100644
index 0000000..3f49b8d
--- /dev/null
+++ b/migrations/versions/add_density_field.py
@@ -0,0 +1,24 @@
+"""add density field
+
+Revision ID: add_density_field
+Revises: initial
+Create Date: 2026-08-05 11:00:00.000000
+
+"""
+from typing import Sequence, Union
+from alembic import op
+import sqlalchemy as sa
+
+
+revision: str = 'add_density_field'
+down_revision: Union[str, None] = 'initial'
+branch_labels: Union[str, Sequence[str], None] = None
+depends_on: Union[str, Sequence[str], None] = None
+
+
+def upgrade() -> None:
+    op.add_column('detections', sa.Column('density', sa.JSON(), nullable=True))
+
+
+def downgrade() -> None:
+    op.drop_column('detections', 'density')
diff --git a/tests/conftest.py b/tests/conftest.py
new file mode 100644
index 0000000..c05a608
--- /dev/null
+++ b/tests/conftest.py
@@ -0,0 +1,7 @@
+import sys
+from unittest.mock import MagicMock, patch
+
+mock_psycopg = MagicMock()
+mock_boto3 = MagicMock()
+
+patch.dict("sys.modules", {"psycopg": mock_psycopg, "boto3": mock_boto3}).start()
diff --git a/tests/test_sink.py b/tests/test_sink.py
index 0cc13e2..eea21ad 100644
--- a/tests/test_sink.py
+++ b/tests/test_sink.py
@@ -39,27 +39,20 @@ class FakeConnection:
         return self
 
     def __exit__(self, exc_type, exc_value, traceback):
         pass
 
     def commit(self):
         self.committed = True
 
 
 def test_postgres_sink(monkeypatch):
-    import sys
-    import types
-
-    if "psycopg" not in sys.modules or sys.modules["psycopg"] is None:
-        dummy_psycopg = types.ModuleType("psycopg")
-        sys.modules["psycopg"] = dummy_psycopg
-
     import psycopg
     from flowsense.sink import PostgresSink
 
     conn = FakeConnection()
     monkeypatch.setattr(psycopg, "connect", lambda url: conn, raising=False)
 
 
     sink = PostgresSink("fake_url")
     sink.emit({
         "ts": 100,
@@ -79,27 +72,20 @@ def test_postgres_sink(monkeypatch):
 
 class FakeS3Client:
     def __init__(self):
         self.uploads = []
 
     def put_object(self, Bucket, Key, Body, ContentType):
         self.uploads.append((Bucket, Key, Body, ContentType))
 
 
 def test_s3_snapshot_sink(monkeypatch):
-    import sys
-    import types
-
-    if "boto3" not in sys.modules or sys.modules["boto3"] is None:
-        dummy_boto3 = types.ModuleType("boto3")
-        sys.modules["boto3"] = dummy_boto3
-
     import boto3
     from flowsense.sink import S3SnapshotSink
 
     client = FakeS3Client()
     monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client, raising=False)
 
     sink = S3SnapshotSink(endpoint_url="http://x", access_key="a", secret_key="b", bucket="snaps")
     sink.save("cam1", 100.5, b"img")
 
     assert len(client.uploads) == 1
