"""Tests for FlowSense → SUMO traffic demand adapter."""
import json

from flowsense.simulation.adapter import (
    aggregate_flows,
    lane_to_direction,
    load_records,
)


def test_lane_to_direction_defaults():
    assert lane_to_direction("kota") == "south"
    assert lane_to_direction("ploso") == "north"
    assert lane_to_direction("demak") == "west"
    assert lane_to_direction("sekoe") == "east"


def test_lane_to_direction_custom_map():
    custom = {"uptown": "north", "downtown": "south"}
    assert lane_to_direction("uptown", lane_map=custom) == "north"


def test_lane_to_direction_unknown_raises():
    import pytest
    with pytest.raises(KeyError, match="Unknown lane name"):
        lane_to_direction("nonexistent")


def test_load_records_missing_file(tmp_path):
    assert load_records(tmp_path / "nope.jsonl") == []


def test_load_records_filters_by_ts(tmp_path):
    p = tmp_path / "data.jsonl"
    lines = [
        json.dumps({"ts": 100, "camera_id": 30, "total_vehicles": 1, "per_lane": {}}),
        json.dumps({"ts": 200, "camera_id": 30, "total_vehicles": 2, "per_lane": {}}),
        json.dumps({"ts": 300, "camera_id": 30, "total_vehicles": 3, "per_lane": {}}),
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    result = load_records(p, start_ts=150, end_ts=250)
    assert len(result) == 1
    assert result[0]["ts"] == 200


def test_load_records_sorted(tmp_path):
    p = tmp_path / "data.jsonl"
    lines = [
        json.dumps({"ts": 300, "total_vehicles": 3, "per_lane": {}}),
        json.dumps({"ts": 100, "total_vehicles": 1, "per_lane": {}}),
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    result = load_records(p)
    assert result[0]["ts"] == 100
    assert result[1]["ts"] == 300


def test_aggregate_flows_with_crossings():
    records = [
        {"ts": 0, "per_lane": {"kota": 2}, "crossings": {"kota": 0, "ploso": 0}},
        {"ts": 450, "per_lane": {"kota": 3}, "crossings": {"kota": 10, "ploso": 5}},
        {"ts": 899, "per_lane": {"kota": 1}, "crossings": {"kota": 20, "ploso": 12}},
    ]
    flows = aggregate_flows(records, bin_seconds=900)
    # All records fall in bin 0 (0-900s)
    # kota (south): delta = 20 - 0 = 20 vehicles in 900s → 80 vph
    # ploso (north): delta = 12 - 0 = 12 vehicles in 900s → 48 vph
    assert len(flows["south"]) == 1
    assert flows["south"][0][2] == 80  # 20 * (3600/900)
    assert flows["north"][0][2] == 48  # 12 * (3600/900)


def test_aggregate_flows_empty_records():
    assert aggregate_flows([]) == {}


def test_aggregate_flows_minimum_vph():
    """P1-13: genuinely empty directions must yield 0 vph, not a fabricated minimum.

    Previously this asserted a forced minimum of 10 vph for empty directions,
    which invented traffic that does not exist. After the fix, an empty direction
    produces vph=0.
    """
    records = [
        {"ts": 0, "per_lane": {"kota": 0}, "crossings": {"kota": 0}},
        {"ts": 899, "per_lane": {"kota": 0}, "crossings": {"kota": 0}},
    ]
    flows = aggregate_flows(records, bin_seconds=900)
    # kota (south): 0 crossings → 0 vph
    assert flows["south"][0][2] == 0
    # ploso/demak/sekoe: no data → 0 vph (not a fabricated 10)
    assert flows["north"][0][2] == 0
    assert flows["west"][0][2] == 0
    assert flows["east"][0][2] == 0


def test_aggregate_flows_crossing_reset_yields_traffic():
    """Codex P1 fix: a cumulative counter with resets must NOT collapse to 0.

    kota counts 1->5 then resets 5->0->5 repeatedly; the old last-first delta
    over the bin was 0. The fixed logic sums positive steps and treats each
    reset as a wrap, so the lane carries real vph and silent lanes stay 0.
    """
    records = [
        {"ts": 0,   "total_vehicles": 2, "crossings": {"kota": 1}},
        {"ts": 2,   "total_vehicles": 2, "crossings": {"kota": 5}},   # +4
        {"ts": 4,   "total_vehicles": 4, "crossings": {"kota": 0}},   # reset
        {"ts": 6,   "total_vehicles": 4, "crossings": {"kota": 5}},   # +5 (post-reset)
        {"ts": 8,   "total_vehicles": 3, "crossings": {"kota": 0}},   # reset
        {"ts": 10,  "total_vehicles": 2, "crossings": {"kota": 3}},   # +3
    ]
    flows = aggregate_flows(records, bin_seconds=900)
    # south (kota): 4 + 5 + 3 = 12 vehicles in 900s -> 48 vph
    assert flows["south"][0][2] == 48
    # ploso/demak/sekoe have no crossings data -> 0 vph (not fabricated)
    assert flows["north"][0][2] == 0
    assert flows["west"][0][2] == 0
    assert flows["east"][0][2] == 0


def test_aggregate_flows_silent_lanes_zero_on_real_data():
    """Regression: with real connector data only kota is instrumented; the
    other three directions must be 0, not invented traffic."""
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "data" / "connector_30.jsonl"
    if not p.exists():
        import pytest
        pytest.skip("connector_30.jsonl not present")
    from flowsense.simulation.adapter import load_records
    recs = load_records(p)
    flows = aggregate_flows(recs, bin_seconds=900)
    # Every direction key present; at least one bin has data.
    assert set(flows) == {"north", "south", "east", "west"}
    total_south = sum(v for _, _, v in flows["south"])
    # south (kota) carries real crossings-derived volume
    assert total_south > 0
    # ploso/demak/sekoe are never instrumented in this capture -> all-zero
    assert all(v == 0 for _, _, v in flows["north"])
    assert all(v == 0 for _, _, v in flows["west"])
    assert all(v == 0 for _, _, v in flows["east"])


def test_aggregate_flows_fallback_uses_total_vehicles_not_occupancy():
    """No crossings field: use total_vehicles, split by per_lane occupancy share."""
    records = [
        {"ts": 0,   "total_vehicles": 10, "per_lane": {"kota": 3, "ploso": 1}},
        {"ts": 2,   "total_vehicles": 10, "per_lane": {"kota": 3, "ploso": 1}},
    ]
    flows = aggregate_flows(records, bin_seconds=900)
    # 20 total vehicles, split 3:1 -> south 15, north 5 (NOT scaled to vph as occupancy)
    assert flows["south"][0][2] == 15 * 4   # *scale(4)
    assert flows["north"][0][2] == 5 * 4
    # unobserved directions stay 0
    assert flows["east"][0][2] == 0
    assert flows["west"][0][2] == 0

    """Wiring test: adapter output must plug directly into SUMO demand."""
    from flowsense.simulation import sim_config

    flows = {
        "south": [(0, 900, 80)],
        "north": [(0, 900, 48)],
        # west/east omitted → must stay empty, not crash
    }
    sim_config.set_real_traffic_volumes(flows)
    assert sim_config.TRAFFIC_VOLUME["south"] == [(0, 900, 80)]
    assert sim_config.TRAFFIC_VOLUME["north"] == [(0, 900, 48)]
    assert sim_config.TRAFFIC_VOLUME["west"] == []
    assert sim_config.TRAFFIC_VOLUME["east"] == []
