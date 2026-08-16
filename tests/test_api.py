import pytest
import requests

from flowsense.cctv_client import fetch_cameras, find_camera
from flowsense.config import Config


class FakeResponse:
    def __init__(self, payload=None, exc=None, status=200):
        self._payload = payload
        self._exc = exc
        self._status = status

    def raise_for_status(self):
        if self._exc:
            raise self._exc
        if self._status >= 400:
            raise requests.HTTPError(f"status {self._status}")

    def json(self):
        if self._exc:
            raise self._exc
        return self._payload


class FakeSession:
    """Returns queued responses; callable entries can raise."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        item = self._responses.pop(0)
        return item() if callable(item) else item


def test_fetch_cameras_success():
    sess = FakeSession([FakeResponse({"success": True, "camera": [{"id": 30, "nama": "Simpang"}]})])
    cams = fetch_cameras(Config(), session=sess)
    assert cams == [{"id": 30, "nama": "Simpang"}]
    assert sess.calls == 1


def test_fetch_cameras_retries_then_succeeds():
    cfg = Config(api_retries=3, api_backoff=0.0)
    boom = lambda: FakeResponse(exc=ConnectionError("down"))
    sess = FakeSession([boom, boom, FakeResponse({"success": True, "camera": []})])
    assert fetch_cameras(cfg, session=sess) == []
    assert sess.calls == 3


def test_fetch_cameras_gives_up():
    cfg = Config(api_retries=2, api_backoff=0.0)
    boom = lambda: FakeResponse(exc=ConnectionError("down"))
    sess = FakeSession([boom, boom])
    with pytest.raises(RuntimeError, match="after 2 attempts"):
        fetch_cameras(cfg, session=sess)


def test_fetch_cameras_raises_on_api_failure():
    sess = FakeSession([FakeResponse({"success": False, "error": "nope"})])
    with pytest.raises(RuntimeError, match="API failed"):
        fetch_cameras(Config(), session=sess)


def test_find_camera_by_id_and_name():
    cameras = [
        {"id": 30, "nama": "Simpang DPRD Arah Kota"},
        {"id": 31, "nama": "Simpang Ploso"},
    ]
    assert find_camera(cameras, cam_id=30)["nama"].startswith("Simpang")
    assert find_camera(cameras, name="ploso")["id"] == 31
    assert find_camera(cameras, name="SIMpang")["id"] == 30


def test_find_camera_errors():
    cameras = [{"id": 30, "nama": "Simpang"}]
    with pytest.raises(RuntimeError):
        find_camera(cameras, cam_id=99)
    with pytest.raises(RuntimeError):
        find_camera(cameras, name="nope")
    with pytest.raises(RuntimeError):
        find_camera(cameras)
