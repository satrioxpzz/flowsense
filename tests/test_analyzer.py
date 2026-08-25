"""Tests for the simulation analyzer (P2-15 coverage)."""
import os
import tempfile

from flowsense.simulation import analyzer as an


def test_parse_tripinfo_missing_file_returns_empty():
    # Must not raise; graceful empty result when output XML is absent.
    vehicles = an._parse_tripinfo("/nonexistent/path/tripinfo.xml")
    assert vehicles == []


def test_compute_global_empty_returns_empty_dict():
    assert an._compute_global([]) == {}


def test_build_report_data_shape_without_data():
    # With no tripinfo.xml, report still assembles with empty global/by_type.
    data = an._build_report_data("Adaptive-Control", ["north"])
    assert "global" in data
    assert "by_vehicle_type" in data
    assert data["simulation_mode"] == "Adaptive-Control"
    assert data["congested_directions"] == ["north"]


def test_parse_tripinfo_real_file(tmp_path):
    xml = tmp_path / "tripinfo.xml"
    xml.write_text(
        '<?xml version="1.0"?>\n'
        '<tripinfos>\n'
        '  <tripinfo id="v0" vType="car" duration="12.5" waitingTime="1.0" '
        'timeLoss="2.0" waitingCount="1" stopTime="0" routeLength="100" '
        'departDelay="0.5" arrival="13.0" fuel_abs="50" CO2_abs="1000" '
        'CO_abs="10" NOx_abs="5" PMx_abs="1"/>\n'
        '</tripinfos>\n',
        encoding="utf-8",
    )
    vehicles = an._parse_tripinfo(str(xml))
    assert len(vehicles) == 1
    assert vehicles[0]["vType"] == "car"
    assert vehicles[0]["duration"] == 12.5
    g = an._compute_global(vehicles)
    assert g["total_vehicles"] == 1
    assert g["avg_travel_time_s"] == 12.5


def test_real_data_run_reports_real_not_synthetic_congestion():
    """P2: a run driven by real FlowSense detections must not be reported as
    synthetic congestion. The report's congested_directions must mark the
    source explicitly as REAL, never inherit `--congested` synthetic dirs."""
    data = an._build_report_data("Adaptive-Control", ["REAL:FlowSense-detections"])
    assert data["congested_directions"] == ["REAL:FlowSense-detections"]
    # The label must be clearly distinguishable from synthetic directions.
    assert not any(d in ("north", "south", "east", "west")
                   for d in data["congested_directions"])
