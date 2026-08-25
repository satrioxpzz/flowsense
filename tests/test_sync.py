"""Tests for the FlowSense storage sync manager (P2: rotate_detections wiring)."""
from pathlib import Path

from flowsense.storage.sync import FlowSenseSyncManager


def _make_manager(tmp_path):
    """Build a manager with a no-op Garage client so nothing touches network."""
    mgr = FlowSenseSyncManager(
        data_dir=str(tmp_path),
        model_path="yolo11n.pt",
        config_dir=str(tmp_path),
    )
    # Neutralize the Garage client so sync_configs/sync_models/sync_detections
    # don't attempt real uploads during the rotate test.
    mgr.client.ensure_bucket = lambda: True
    mgr.client.upload_file = lambda *a, **k: True
    return mgr


def test_rotate_detections_renames_nonempty_connector_file(tmp_path):
    live = tmp_path / "connector_30.jsonl"
    live.write_text('{"ts":1}\n', encoding="utf-8")

    mgr = _make_manager(tmp_path)
    mgr.rotate_detections()

    rotated = list(tmp_path.glob("connector_*.jsonl"))
    # The live file is moved into a date-stamped closed copy...
    assert not live.exists(), "live connector file should have been rotated away"
    # ...and one closed copy now exists.
    assert len(rotated) == 1
    assert rotated[0].name.startswith("connector_30.20")  # YYYY-MM-DD stamp


def test_rotate_detections_skips_empty_file(tmp_path):
    live = tmp_path / "connector_30.jsonl"
    live.write_text("", encoding="utf-8")  # empty -> still being appended to

    mgr = _make_manager(tmp_path)
    mgr.rotate_detections()

    # Empty live file is left untouched (would break the connector's append).
    assert live.exists()
    assert live.read_text(encoding="utf-8") == ""
    assert not list(tmp_path.glob("connector_30.20*.jsonl"))


def test_sync_now_invokes_rotate_detections(tmp_path):
    live = tmp_path / "connector_30.jsonl"
    live.write_text('{"ts":1}\n', encoding="utf-8")

    mgr = _make_manager(tmp_path)
    mgr.sync_now()  # must rotate before syncing detections

    # After a full sync_now, the live file should have been rotated.
    assert not live.exists()
    assert list(tmp_path.glob("connector_30.20*.jsonl"))
