"""Tests for the live ops dashboard data snapshot (no DB required)."""
from flowsense.api_server.routes.dashboard import _snapshot, _read_jsonl, DATA_DIR


def test_read_jsonl_missing():
    assert _read_jsonl(DATA_DIR / "does_not_exist.jsonl") == []


def test_snapshot_structure():
    snap = _snapshot()
    assert "cameras" in snap and "kpis" in snap and "alerts" in snap
    for cam in snap["cameras"]:
        assert {"id", "name", "status", "lanes", "total", "spark"} <= cam.keys()
        assert cam["status"] in ("ok", "warn", "crit")
        assert isinstance(cam["spark"], list)
    k = snap["kpis"]
    assert {"vehicles_per_min", "active_cameras", "alerts", "critical",
            "avg_density_pct"} <= k.keys()
