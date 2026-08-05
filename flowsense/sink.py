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


class PostgresSink(RecordSink):
    def __init__(self, conn_str: str):
        self.conn_str = conn_str

    def emit(self, record: dict):
        import psycopg
        from datetime import datetime, timezone

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
                        json.dumps(record.get("density", {})),
                    ),
                )
            conn.commit()


class S3SnapshotSink(SnapshotSink):
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str):
        import boto3

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )

    def save(self, camera_id: str, ts: float, frame_bytes: bytes):
        key = f"snapshots/{camera_id}/{camera_id}_{int(ts)}.jpg"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=frame_bytes,
            ContentType="image/jpeg",
        )


