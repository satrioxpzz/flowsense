# Task 1 Report: Add dependencies and Sink interfaces

## What was implemented
1. **Updated `requirements.txt`**: Added `psycopg[binary]==3.1.18` to the dependencies (boto3 was already present).
2. **Created `flowsense/sink.py`**:
   - `RecordSink`: Abstract base class with `emit(self, record: dict)`
   - `JsonlSink(RecordSink)`: Concrete sink writing JSON lines to specified filepath, creating parent directories as needed and flushing per record.
   - `SnapshotSink`: Abstract base class with `save(self, camera_id: str, ts: float, frame_bytes: bytes)`

## What was tested and test results
- Created `tests/test_sink.py` containing `test_jsonl_sink_emits`.
- Confirmed test failure prior to implementation (ModuleNotFoundError).
- Ran full test suite via `pytest`: 71 passed, 0 failed.

## Files changed
- Modified: `requirements.txt`
- Created: `flowsense/sink.py`
- Created: `tests/test_sink.py`

## Self-review findings
- Implementation strictly matches the specified task brief and interface contracts.
- Code is minimal, robust, and clean.
- `git add/commit` commands required interactive terminal permissions which timed out in subagent mode, so files are modified/created in the working directory ready for commit if not automatically committed.
