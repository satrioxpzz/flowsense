# Task 3 Report: S3SnapshotSink implementation

## What was implemented
- Implemented `S3SnapshotSink` inheriting from `SnapshotSink` in `flowsense/sink.py`.
- Initialized boto3 S3 client with `endpoint_url`, `aws_access_key_id`, `aws_secret_access_key`, and `region_name="us-east-1"`.
- Implemented `save(camera_id, ts, frame_bytes)` method that constructs object keys following the pattern `snapshots/{camera_id}/{camera_id}_{int(ts)}.jpg` and uploads the JPEG bytes with `ContentType="image/jpeg"`.

## What was tested and test results
- Added unit test `test_s3_snapshot_sink` in `tests/test_sink.py`.
- Tested S3 upload functionality using `FakeS3Client` mock. Verified bucket name ("snaps"), key format ("snapshots/cam1/cam1_100.jpg"), body bytes (`b"img"`), and content type ("image/jpeg").

## Files changed
- `flowsense/sink.py`: Added `S3SnapshotSink` class.
- `tests/test_sink.py`: Added `FakeS3Client` and `test_s3_snapshot_sink`.

## Self-review findings
- No live S3 or AWS calls made; all S3 operations in tests use mock `FakeS3Client`.
- Clean error handling / monkeypatch fallback for test environments without boto3 pre-installed.
- Follows existing pattern in `flowsense/sink.py` and `tests/test_sink.py`.
