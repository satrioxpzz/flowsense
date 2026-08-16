"""Tests for API auth (P1-6 / P1-7) and pagination wiring (P2-8).

These exercise the security dependency directly (no live Postgres / no app
lifespan DB connection required).
"""
import importlib

import pytest

from flowsense.database import security
from flowsense.api_server import routes as api_routes


def _reload_with_key(key):
    # Force the module to read the new env var for the expected key.
    import os
    os.environ["FLOWSENSE_INBOUND_API_KEY"] = key
    importlib.reload(security)
    return security


def test_missing_key_is_forbidden():
    sec = _reload_with_key("real-key")
    with pytest.raises(Exception) as exc:
        # No api_key passed -> treated as missing/None -> 403.
        import asyncio
        asyncio.get_event_loop().run_until_complete(sec.require_api_key(api_key=None))
    assert exc.value.status_code == 403


def test_wrong_key_is_forbidden():
    sec = _reload_with_key("real-key")
    import asyncio
    with pytest.raises(Exception) as exc:
        asyncio.get_event_loop().run_until_complete(sec.require_api_key(api_key="nope"))
    assert exc.value.status_code == 403


def test_correct_key_accepted():
    sec = _reload_with_key("real-key")
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        sec.require_api_key(api_key="real-key"))
    assert result == "real-key"


def test_write_routers_use_require_api_key():
    # Every mutating router must reference require_api_key as a Depends default
    # on its write routes (POST/PUT/DELETE/PATCH).
    import inspect
    for name, mod in (
        ("cameras", api_routes.cameras),
        ("detections", api_routes.detections),
        ("intersections", api_routes.intersections),
        ("alerts", api_routes.alerts),
    ):
        src = inspect.getsource(mod)
        # Count write routes that depend on require_api_key.
        n = src.count("Depends(require_api_key)")
        assert n >= 1, f"{name} has no Depends(require_api_key) on a write route"


def test_list_routes_declare_pagination_params():
    # P2-8: list endpoints must accept limit/offset (present in route signature).
    import inspect
    from flowsense.api_server.routes import detections, alerts, cameras
    for mod in (detections, alerts, cameras):
        sig = inspect.signature(mod.list_detections if mod is detections
                                else mod.list_alerts if mod is alerts
                                else mod.list_cameras)
        params = set(sig.parameters)
        assert {"limit", "offset"} <= params, f"{mod.__name__} list missing pagination"
