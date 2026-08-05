from flowsense.runner import build_record, parse_args, per_lane_present

CAMERA = {"id": 30, "nama": "Simpang DPRD Arah Kota"}


def test_build_record_plain():
    r = build_record(
        100.9,
        CAMERA,
        {"total_vehicles": 3, "per_lane": {"kota": 2}, "vehicles": []},
    )
    assert r["ts"] == 100
    assert r["camera_id"] == 30
    assert r["camera"] == "Simpang DPRD Arah Kota"
    assert r["total_vehicles"] == 3
    assert r["per_lane"] == {"kota": 2}
    assert "crossings" not in r


def test_build_record_with_crossings():
    r = build_record(
        100.0,
        CAMERA,
        {"total_vehicles": 0, "per_lane": {}, "vehicles": []},
        crossings={"kota": 5},
    )
    assert r["crossings"] == {"kota": 5}


def test_per_lane_present():
    dets = [
        {"lane": "kota"},
        {"lane": "kota"},
        {"lane": "ploso"},
        {"lane": None},
    ]
    assert per_lane_present(dets) == {"kota": 2, "ploso": 1}


def test_parse_args_keeps_legacy_flags():
    args = parse_args(["--camera-id", "30", "--snapshot-only", "--track"])
    assert args.camera_id == "30"
    assert args.snapshot_only is True
    assert args.track is True
    assert args.log_json is True


def test_build_record_with_density():
    r = build_record(
        100.0,
        CAMERA,
        {"total_vehicles": 0, "per_lane": {}, "vehicles": []},
        density={"kota": "sedang"}
    )
    assert r["density"] == {"kota": "sedang"}
