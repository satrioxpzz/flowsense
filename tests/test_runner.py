from flowsense.runner import build_record, parse_args, per_lane_present, VisionClassifier

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


def test_parse_args_sink_and_snapshot():
    args = parse_args(["--sink", "jsonl,postgres", "--snapshot"])
    assert args.sink == "jsonl,postgres"
    assert args.snapshot is True


def test_parse_args_vision_flags():
    args = parse_args(["--vision", "--vision-interval", "45"])
    assert args.vision is True
    assert args.vision_interval == 45.0


def test_build_record_with_pedestrians_vision():
    r = build_record(
        100.0,
        CAMERA,
        {"total_vehicles": 0, "per_lane": {}},
        pedestrians=[
            {"track_id": 7, "vision": {"has_mobility_aid": True, "aid_type": "wheelchair"}},
            {"track_id": 8, "vision": {"has_mobility_aid": False, "aid_type": "none"}},
            {"track_id": 9},
        ],
    )
    assert r["pedestrians"] == 3
    assert r["vision"] == [
        {"track_id": 7, "has_mobility_aid": True, "aid_type": "wheelchair"},
        {"track_id": 8, "has_mobility_aid": False, "aid_type": "none"},
    ]


def test_build_record_without_pedestrians_omits_vision():
    r = build_record(100.0, CAMERA, {"total_vehicles": 0, "per_lane": {}})
    assert "pedestrians" not in r
    assert "vision" not in r


def test_vision_classifier_caching(tmp_path, monkeypatch):
    import numpy as np
    import flowsense.runner as runner
    from unittest.mock import patch

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    vc = VisionClassifier(tmp_path / "crops", cooldown=30.0)
    det = {"bbox": [10, 10, 40, 90], "track_id": 7}

    with patch("flowsense.runner.cv2.imwrite", return_value=True) as mock_im, \
         patch.object(runner, "crop_bbox", return_value=frame), \
         patch("flowsense.ollama_vision.detect_accessibility_needs",
               return_value={"aid_type": "wheelchair", "has_mobility_aid": True}) as mock_detect:
        r1 = vc.classify(det, frame, now=1000.0)
        r2 = vc.classify(det, frame, now=1005.0)
    assert r1 == r2
    assert mock_detect.call_count == 1


def test_main_with_sinks(tmp_path, monkeypatch):
    import numpy as np
    from unittest.mock import MagicMock, patch

    out_file = tmp_path / "test_out.jsonl"
    monkeypatch.setenv("FLOWSENSE_DB_URL", "postgresql://localhost/testdb")
    monkeypatch.setenv("FLOWSENSE_S3_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("FLOWSENSE_S3_ACCESS_KEY", "access")
    monkeypatch.setenv("FLOWSENSE_S3_SECRET_KEY", "secret")
    monkeypatch.setenv("FLOWSENSE_S3_BUCKET", "bucket")

    fake_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    mock_stream = MagicMock()
    mock_stream.read.return_value = (True, fake_frame)

    with patch("flowsense.runner.ReconnectingStream", return_value=mock_stream), \
         patch("flowsense.runner.PostgresSink") as mock_pg_cls, \
         patch("flowsense.runner.S3SnapshotSink") as mock_s3_cls:

        mock_pg_instance = MagicMock()
        mock_pg_cls.return_value = mock_pg_instance
        mock_s3_instance = MagicMock()
        mock_s3_cls.return_value = mock_s3_instance

        from flowsense.runner import main
        ret = main([
            "--url", "http://fake.stream/live.m3u8",
            "--skip-detect",
            "--snapshot-only",
            "--sink", "jsonl,postgres",
            "--snapshot",
            "--out", str(out_file),
        ])

        assert ret == 0
        assert out_file.exists()
        assert mock_pg_instance.emit.called
        assert mock_s3_instance.save.called

