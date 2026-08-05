# FlowSense Database and Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement database and storage sinks for FlowSense records and snapshots to integrate with PostgreSQL/TimescaleDB and Garage (S3).

**Architecture:** We will introduce a `RecordSink` and `SnapshotSink` interface in `flowsense/sink.py`. `runner.py` will be refactored to support multiple sinks. We will implement `PostgresSink` for DB insertion and `S3SnapshotSink` for uploading snapshot images to Garage. Finally, we will update the database models to include the `density` field.

**Tech Stack:** Python 3.13, psycopg (psycopg3), boto3, pytest.

## Global Constraints

- **No live DB or S3 for tests:** Tests must use mocks for psycopg and boto3. No network calls.
- **Dependencies:** `psycopg[binary]` and `boto3` must be added to `requirements.txt`. (Assume `boto3` is already present, but ensure it's there).
- **CLI compatibility:** Existing `--out` file writing must still work, defaulting to `.jsonl`.
- **Database Schema:** We insert into the `detections` table.
- Commit after every task. Repo has existing commits; all work happens on the current branch.

---

### Task 1: Add dependencies and Sink interfaces

**Files:**
- Modify: `requirements.txt`
- Create: `flowsense/sink.py`
- Create: `tests/test_sink.py`

**Interfaces:**
- Produces: 
  - `class RecordSink` with method `def emit(self, record: dict)`
  - `class JsonlSink(RecordSink)` with `__init__(self, filepath)`
  - `class SnapshotSink` with method `def save(self, camera_id: str, ts: float, frame_bytes: bytes)`

- [ ] **Step 1: Update requirements.txt**

Ensure `psycopg[binary]==3.1.18` and `boto3` are in `requirements.txt`.
Run `pip install -r requirements.txt`.

- [ ] **Step 2: Write failing tests for sinks**

Create `tests/test_sink.py`:
```python
import json
from flowsense.sink import JsonlSink

def test_jsonl_sink_emits(tmp_path):
    p = tmp_path / "out.jsonl"
    sink = JsonlSink(p)
    sink.emit({"ts": 100})
    sink.emit({"ts": 200})
    lines = p.read_text().splitlines()
    assert json.loads(lines[0]) == {"ts": 100}
    assert json.loads(lines[1]) == {"ts": 200}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_sink.py -v`

- [ ] **Step 4: Implement the minimal module**

Create `flowsense/sink.py`:
```python
import json
from pathlib import Path

class RecordSink:
    def emit(self, record: dict):
        raise NotImplementedError

class JsonlSink(RecordSink):
    def __init__(self, filepath):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
    
    def emit(self, record: dict):
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
            f.flush()

class SnapshotSink:
    def save(self, camera_id: str, ts: float, frame_bytes: bytes):
        raise NotImplementedError
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sink.py -v`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt flowsense/sink.py tests/test_sink.py
git commit -m "feat: add psycopg and Sink interfaces"
```

---

### Task 2: PostgresSink implementation

**Files:**
- Modify: `flowsense/sink.py`
- Modify: `tests/test_sink.py`

**Interfaces:**
- Produces: `class PostgresSink(RecordSink)` with `__init__(self, conn_str)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sink.py`:
```python
from flowsense.sink import PostgresSink
from datetime import datetime

class FakeCursor:
    def __init__(self):
        self.execs = []
    def execute(self, query, params):
        self.execs.append((query, params))

class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False
    def cursor(self):
        return self.cursor_obj
    def commit(self):
        self.committed = True

def test_postgres_sink(monkeypatch):
    import psycopg
    conn = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda url: conn)
    
    sink = PostgresSink("fake_url")
    sink.emit({
        "ts": 100, 
        "camera_id": 30, 
        "total_vehicles": 2, 
        "per_lane": {}, 
        "crossings": {},
        "density": {}
    })
    
    q, p = conn.cursor_obj.execs[0]
    assert "INSERT INTO detections" in q
    assert p[0] == 30 # camera_id
    assert p[2] == 2 # total_vehicles
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_sink.py -v`

- [ ] **Step 3: Implement PostgresSink**

Append to `flowsense/sink.py`:
```python
import psycopg
from datetime import datetime, timezone

class PostgresSink(RecordSink):
    def __init__(self, conn_str: str):
        self.conn_str = conn_str
    
    def emit(self, record: dict):
        # We open and close the connection for now to keep it simple, 
        # or use a persistent connection if needed. For simplicity:
        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                ts = datetime.fromtimestamp(record["ts"], tz=timezone.utc)
                cur.execute(
                    "INSERT INTO detections (camera_id, timestamp, total_vehicles, per_lane, crossings, density) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        record["camera_id"], 
                        ts, 
                        record["total_vehicles"], 
                        json.dumps(record.get("per_lane", {})), 
                        json.dumps(record.get("crossings", {})),
                        json.dumps(record.get("density", {}))
                    )
                )
            conn.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_sink.py -v`

- [ ] **Step 5: Commit**

```bash
git add flowsense/sink.py tests/test_sink.py
git commit -m "feat: add PostgresSink for database ingestion"
```

---

### Task 3: S3SnapshotSink implementation

**Files:**
- Modify: `flowsense/sink.py`
- Modify: `tests/test_sink.py`

**Interfaces:**
- Produces: `class S3SnapshotSink(SnapshotSink)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sink.py`:
```python
from flowsense.sink import S3SnapshotSink

class FakeS3Client:
    def __init__(self):
        self.uploads = []
    def put_object(self, Bucket, Key, Body, ContentType):
        self.uploads.append((Bucket, Key, Body, ContentType))

def test_s3_snapshot_sink(monkeypatch):
    import boto3
    client = FakeS3Client()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    
    sink = S3SnapshotSink(endpoint_url="http://x", access_key="a", secret_key="b", bucket="snaps")
    sink.save("cam1", 100.5, b"img")
    
    assert len(client.uploads) == 1
    bucket, key, body, ctype = client.uploads[0]
    assert bucket == "snaps"
    assert "cam1_100" in key
    assert body == b"img"
    assert ctype == "image/jpeg"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_sink.py -v`

- [ ] **Step 3: Implement S3SnapshotSink**

Append to `flowsense/sink.py`:
```python
import boto3

class S3SnapshotSink(SnapshotSink):
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str):
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1"
        )
    
    def save(self, camera_id: str, ts: float, frame_bytes: bytes):
        key = f"snapshots/{camera_id}/{camera_id}_{int(ts)}.jpg"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=frame_bytes,
            ContentType="image/jpeg"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_sink.py -v`

- [ ] **Step 5: Commit**

```bash
git add flowsense/sink.py tests/test_sink.py
git commit -m "feat: add S3SnapshotSink for Garage/disk storage"
```

---

### Task 4: Config and runner.py updates

**Files:**
- Modify: `flowsense/config.py`
- Modify: `flowsense/runner.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: Sinks from `flowsense/sink.py`
- Modifies: `Config` to have DB and S3 settings.

- [ ] **Step 1: Write failing tests for Config**

Add to `tests/test_config.py`:
```python
def test_db_s3_config_defaults(tmp_path):
    from flowsense.config import load_config
    cfg = load_config(env_path=tmp_path / "missing.env")
    assert cfg.db_url == ""
    assert cfg.s3_endpoint == ""
    assert cfg.s3_access_key == ""
    assert cfg.s3_secret_key == ""
    assert cfg.s3_bucket == ""
```

- [ ] **Step 2: Implement Config fields**

In `flowsense/config.py`, add to `Config`:
```python
    db_url: str = ""
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
```
And in `load_config`, read from `FLOWSENSE_DB_URL`, `FLOWSENSE_S3_ENDPOINT`, etc.

- [ ] **Step 3: Update runner.py to use sinks**

In `flowsense/runner.py`:
Replace `out_path` setup and file writing loop with `JsonlSink`.
Add CLI argument `--sink` (default `"jsonl"`, allow `"jsonl,postgres"`).
Add CLI argument `--snapshot` (flag) to save JPEG to `S3SnapshotSink` every interval.
```python
    record_sinks = []
    if "jsonl" in args.sink:
        record_sinks.append(JsonlSink(out_path))
    if "postgres" in args.sink and cfg.db_url:
        record_sinks.append(PostgresSink(cfg.db_url))

    snap_sink = None
    if getattr(args, 'snapshot', False) and cfg.s3_endpoint:
        snap_sink = S3SnapshotSink(cfg.s3_endpoint, cfg.s3_access_key, cfg.s3_secret_key, cfg.s3_bucket)
```
Inside the `if now - last_emit >= cfg.interval:` loop:
```python
                    record = build_record(...)
                    for sink in record_sinks:
                        try:
                            sink.emit(record)
                        except Exception as e:
                            log.error("sink error", exc_info=True)
                    if snap_sink:
                        ok, buf = cv2.imencode('.jpg', frame)
                        if ok:
                            try:
                                snap_sink.save(camera_key, now, buf.tobytes())
                            except Exception as e:
                                log.error("snap error", exc_info=True)
```
Remove `f.write(...)` directly.

- [ ] **Step 4: Commit**

```bash
git add flowsense/config.py flowsense/runner.py tests/test_config.py
git commit -m "feat: wire RecordSink and SnapshotSink into runner"
```

---

### Task 5: Database schema update

**Files:**
- Modify: `flowsense/database/models.py`
- Modify: `flowsense/api_server/schemas.py`

- [ ] **Step 1: Add density field to Detection**

In `flowsense/database/models.py`, `class Detection`:
```python
    density = Column(JSON)
```

In `flowsense/api_server/schemas.py`, `class DetectionBase`:
```python
    density: Optional[Dict[str, Any]] = None
```

- [ ] **Step 2: Commit**

```bash
git add flowsense/database/models.py flowsense/api_server/schemas.py
git commit -m "feat: add density field to Detection schema"
```
