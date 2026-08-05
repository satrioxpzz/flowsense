# Task 2: PostgresSink implementation

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
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_value, traceback):
        pass
    def commit(self):
        self.committed = True

# We need FakeCursor to support context manager too
class FakeCursorContext(FakeCursor):
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_value, traceback):
        pass

FakeConnection.cursor = lambda self: FakeCursorContext()

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
    
    # Actually context manager returns self, so the execs might be on the context
    q, p = conn.cursor().execs[0]
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
