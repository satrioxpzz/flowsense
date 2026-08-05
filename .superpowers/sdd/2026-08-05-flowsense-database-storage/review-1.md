02d17ee feat: add psycopg and Sink interfaces
 flowsense/sink.py  | 20 ++++++++++++++++++++
 requirements.txt   | 30 ++++++++++++++++--------------
 tests/test_sink.py | 11 +++++++++++
 3 files changed, 47 insertions(+), 14 deletions(-)
diff --git a/flowsense/sink.py b/flowsense/sink.py
new file mode 100644
index 0000000..af1a52c
--- /dev/null
+++ b/flowsense/sink.py
@@ -0,0 +1,20 @@
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
diff --git a/tests/test_sink.py b/tests/test_sink.py
new file mode 100644
index 0000000..42304df
--- /dev/null
+++ b/tests/test_sink.py
@@ -0,0 +1,11 @@
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
