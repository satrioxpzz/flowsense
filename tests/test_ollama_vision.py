from flowsense.ollama_vision import _extract_json, detect_accessibility_needs


def test_extract_json_plain():
    assert _extract_json('{"aid_type": "wheelchair"}') == {"aid_type": "wheelchair"}


def test_extract_json_fenced_with_surrounding_text():
    text = 'Sure, here you go:\n```json\n{"aid_type": "cane", "has_mobility_aid": true}\n```\nhope that helps'
    assert _extract_json(text) == {"aid_type": "cane", "has_mobility_aid": True}


def test_extract_json_raises_without_object():
    import pytest
    with pytest.raises(ValueError):
        _extract_json("no json here")


def test_detect_accessibility_needs_falls_back_on_failure(monkeypatch):
    import requests

    def boom(image_path, prompt, timeout=30):
        raise requests.ConnectionError("connect refused")

    monkeypatch.setattr("flowsense.ollama_vision.describe_frame", boom)
    result = detect_accessibility_needs("whatever.jpg")
    assert result["aid_type"] == "unclear"
    assert result["has_mobility_aid"] is None
    assert "failed" in result["notes"]


def test_detect_accessibility_needs_parses_json(monkeypatch):
    monkeypatch.setattr(
        "flowsense.ollama_vision.describe_frame",
        lambda image_path, prompt, timeout=30: '{"has_mobility_aid": false, "aid_type": "none", "notes": "walking unaided"}',
    )
    result = detect_accessibility_needs("whatever.jpg")
    assert result == {"has_mobility_aid": False, "aid_type": "none", "notes": "walking unaided"}