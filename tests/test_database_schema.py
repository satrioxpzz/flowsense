from datetime import datetime, timezone
from flowsense.database.models import Detection
from flowsense.api_server.schemas import DetectionBase, DetectionCreate, DetectionResponse


def test_detection_model_density_column():
    assert hasattr(Detection, "density")
    detection = Detection(
        camera_id=1,
        total_vehicles=10,
        per_lane={"lane1": 5},
        crossings={},
        density={"level": "HIGH", "score": 0.85},
    )
    assert detection.density == {"level": "HIGH", "score": 0.85}


def test_detection_schema_density_optional():
    now = datetime.now(timezone.utc)
    # Test default None
    det_base = DetectionBase(
        camera_id=1,
        timestamp=now,
        total_vehicles=5,
        per_lane={},
        crossings={},
    )
    assert det_base.density is None

    # Test with density dict provided
    det_create = DetectionCreate(
        camera_id=1,
        timestamp=now,
        total_vehicles=5,
        per_lane={},
        crossings={},
        density={"level": "LOW", "score": 0.2},
    )
    assert det_create.density == {"level": "LOW", "score": 0.2}

    det_resp = DetectionResponse(
        id=42,
        camera_id=1,
        timestamp=now,
        total_vehicles=5,
        per_lane={},
        crossings={},
        density={"level": "MEDIUM", "score": 0.5},
    )
    assert det_resp.id == 42
    assert det_resp.density == {"level": "MEDIUM", "score": 0.5}
