"""Tests for simulation controller shared helpers and the manual override (P2-5/P2-11)."""
import threading
import time

import pytest

from flowsense.simulation import controller as ctrl
from flowsense.edge.manual_mode import ManualOverrideController, OverrideState


def test_build_poi_positions_shape():
    pos = ctrl.build_poi_positions(400.0, 400.0)
    assert set(pos.keys()) == {"timer_N", "timer_S", "timer_W", "timer_E"}
    assert pos["timer_N"] == (410.0, 430.0)
    assert pos["timer_S"] == (390.0, 370.0)


def test_create_pois_calls_traci():
    added = []
    class FakePoi:
        @staticmethod
        def add(poi_id, **kwargs):
            added.append(poi_id)
    fake = type("T", (), {"poi": FakePoi})()
    ctrl.create_pois(fake, ctrl.build_poi_positions(0, 0))
    assert sorted(added) == ["timer_E", "timer_N", "timer_S", "timer_W"]


def test_init_simulation_logger_disabled_when_import_fails(monkeypatch):
    # If sim_logger import fails, return None rather than raising.
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name.endswith("sim_logger"):
            raise ImportError("nope")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert ctrl.init_simulation_logger() is None


def test_manual_override_lock_exclusivity():
    m = ManualOverrideController(timeout_seconds=10, audit_log_path=None)
    assert m.lock("alice") is True
    assert m.lock("bob") is False  # alice holds the lock
    assert m.set_override("bob", OverrideState.MANUAL_ALL_RED) is False
    assert m.set_override("alice", OverrideState.MANUAL_ALL_RED) is True
    assert m.unlock("bob") is False
    assert m.unlock("alice") is True
    assert m.state == OverrideState.AUTO


def test_manual_override_get_status_is_non_mutating():
    m = ManualOverrideController(timeout_seconds=10, audit_log_path=None)
    m.lock("alice")
    # Hold a reference to internal state, then call get_status repeatedly.
    before = (m.state, m.lock_owner, m.active_phase)
    for _ in range(5):
        m.get_status()
    after = (m.state, m.lock_owner, m.active_phase)
    assert before == after, "get_status() must not mutate state"


def test_manual_override_persists_audit():
    import tempfile, os, json
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        m = ManualOverrideController(timeout_seconds=10, audit_log_path=__import__("pathlib").Path(path))
        m.lock("alice")
        m.set_override("alice", OverrideState.MANUAL_GREEN_PHASE, phase=2)
        m.unlock("alice")
        lines = [json.loads(l) for l in open(path) if l.strip()]
        actions = [e["action"] for e in lines]
        assert "LOCK" in actions and "SET_OVERRIDE" in actions and "UNLOCK" in actions
    finally:
        os.remove(path)


def test_manual_override_concurrent_locks():
    m = ManualOverrideController(timeout_seconds=60, audit_log_path=None)
    results = []
    def try_lock(user):
        results.append((user, m.lock(user)))
    ts = [threading.Thread(target=try_lock, args=(f"u{i}",)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Exactly one owner across all threads (no lost-update race).
    owners = [u for u, ok in results if ok]
    assert len(owners) == 1
