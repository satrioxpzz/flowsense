# Task 1: Add dependencies and Sink interfaces

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
