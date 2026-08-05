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


class FakeCursor:
    def __init__(self):
        self.execs = []

    def execute(self, query, params):
        self.execs.append((query, params))


class FakeCursorContext(FakeCursor):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursorContext()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def commit(self):
        self.committed = True


def test_postgres_sink(monkeypatch):
    import sys
    import types

    if "psycopg" not in sys.modules or sys.modules["psycopg"] is None:
        dummy_psycopg = types.ModuleType("psycopg")
        sys.modules["psycopg"] = dummy_psycopg

    import psycopg
    from flowsense.sink import PostgresSink

    conn = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda url: conn, raising=False)


    sink = PostgresSink("fake_url")
    sink.emit({
        "ts": 100,
        "camera_id": 30,
        "total_vehicles": 2,
        "per_lane": {},
        "crossings": {},
        "density": {},
    })

    q, p = conn.cursor().execs[0]
    assert "INSERT INTO detections" in q
    assert p[0] == 30  # camera_id
    assert p[2] == 2  # total_vehicles
    assert conn.committed


class FakeS3Client:
    def __init__(self):
        self.uploads = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.uploads.append((Bucket, Key, Body, ContentType))


def test_s3_snapshot_sink(monkeypatch):
    import sys
    import types

    if "boto3" not in sys.modules or sys.modules["boto3"] is None:
        dummy_boto3 = types.ModuleType("boto3")
        sys.modules["boto3"] = dummy_boto3

    import boto3
    from flowsense.sink import S3SnapshotSink

    client = FakeS3Client()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client, raising=False)

    sink = S3SnapshotSink(endpoint_url="http://x", access_key="a", secret_key="b", bucket="snaps")
    sink.save("cam1", 100.5, b"img")

    assert len(client.uploads) == 1
    bucket, key, body, ctype = client.uploads[0]
    assert bucket == "snaps"
    assert "cam1_100" in key
    assert body == b"img"
    assert ctype == "image/jpeg"


