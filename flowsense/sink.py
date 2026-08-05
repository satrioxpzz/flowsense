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
