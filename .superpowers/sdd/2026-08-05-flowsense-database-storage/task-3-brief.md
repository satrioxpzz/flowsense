# Task 3: S3SnapshotSink implementation

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
