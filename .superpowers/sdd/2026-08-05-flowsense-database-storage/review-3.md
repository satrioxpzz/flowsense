5757a2a feat: add S3SnapshotSink for Garage/disk storage
 flowsense/sink.py  | 24 ++++++++++++++++++++++++
 tests/test_sink.py | 34 ++++++++++++++++++++++++++++++++++
 2 files changed, 58 insertions(+)
diff --git a/flowsense/sink.py b/flowsense/sink.py
index 6765f6f..14615bc 100644
--- a/flowsense/sink.py
+++ b/flowsense/sink.py
@@ -38,10 +38,34 @@ class PostgresSink(RecordSink):
                         record["camera_id"],
                         ts,
                         record["total_vehicles"],
                         json.dumps(record.get("per_lane", {})),
                         json.dumps(record.get("crossings", {})),
                         json.dumps(record.get("density", {})),
                     ),
                 )
             conn.commit()
 
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
diff --git a/tests/test_sink.py b/tests/test_sink.py
index 4f2eb63..0cc13e2 100644
--- a/tests/test_sink.py
+++ b/tests/test_sink.py
@@ -69,10 +69,44 @@ def test_postgres_sink(monkeypatch):
         "crossings": {},
         "density": {},
     })
 
     q, p = conn.cursor().execs[0]
     assert "INSERT INTO detections" in q
     assert p[0] == 30  # camera_id
     assert p[2] == 2  # total_vehicles
     assert conn.committed
 
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
