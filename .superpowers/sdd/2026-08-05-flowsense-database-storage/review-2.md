77a1b49 feat: add PostgresSink for database ingestion
 flowsense/sink.py  | 27 ++++++++++++++++++++++
 tests/test_sink.py | 67 ++++++++++++++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 94 insertions(+)
diff --git a/flowsense/sink.py b/flowsense/sink.py
index af1a52c..6765f6f 100644
--- a/flowsense/sink.py
+++ b/flowsense/sink.py
@@ -11,10 +11,37 @@ class JsonlSink(RecordSink):
         self.filepath.parent.mkdir(parents=True, exist_ok=True)
 
     def emit(self, record: dict):
         with open(self.filepath, "a", encoding="utf-8") as f:
             f.write(json.dumps(record, separators=(",", ":")) + "\n")
             f.flush()
 
 class SnapshotSink:
     def save(self, camera_id: str, ts: float, frame_bytes: bytes):
         raise NotImplementedError
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
diff --git a/tests/test_sink.py b/tests/test_sink.py
index 42304df..4f2eb63 100644
--- a/tests/test_sink.py
+++ b/tests/test_sink.py
@@ -2,10 +2,77 @@ import json
 from flowsense.sink import JsonlSink
 
 def test_jsonl_sink_emits(tmp_path):
     p = tmp_path / "out.jsonl"
     sink = JsonlSink(p)
     sink.emit({"ts": 100})
     sink.emit({"ts": 200})
     lines = p.read_text().splitlines()
     assert json.loads(lines[0]) == {"ts": 100}
     assert json.loads(lines[1]) == {"ts": 200}
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
