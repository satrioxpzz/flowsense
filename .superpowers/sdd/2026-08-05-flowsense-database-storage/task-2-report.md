# Task 2 Report: PostgresSink Implementation

## What was implemented
- Implemented `PostgresSink(RecordSink)` in `flowsense/sink.py` which consumes detection records and emits them into PostgreSQL `detections` table using `psycopg`.
- Formats `record["ts"]` into UTC `datetime` objects and serializes `per_lane`, `crossings`, and `density` dictionaries to JSON strings using `json.dumps`.

## What was tested and test results
- Added `test_postgres_sink` to `tests/test_sink.py` with mock `FakeConnection` and `FakeCursorContext`.
- Verified test failure prior to implementation (`ImportError: cannot import name 'PostgresSink'`).
- Verified test pass after implementation.
- Executed `python -m pytest`: 72 tests passed cleanly (71 existing + 1 new PostgresSink test).

## Files changed
- `flowsense/sink.py`: Added `PostgresSink` class.
- `tests/test_sink.py`: Added `FakeCursor`, `FakeCursorContext`, `FakeConnection`, and `test_postgres_sink`.

## Self-review findings
- Zero breaking changes to `RecordSink` or `JsonlSink`.
- Lazy import of `psycopg` inside `emit` avoids import failures if `psycopg` is missing during other unit tests.
- Connection and cursor are properly cleaned up using Python context managers (`with psycopg.connect(...)`, `with conn.cursor()`).
- All 72 project tests pass cleanly in 0.77s.
