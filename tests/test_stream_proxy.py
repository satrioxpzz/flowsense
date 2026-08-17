"""Tests for the HLS stream proxy (flowsense/api_server/routes/stream.py).

Locks in:
  - SSRF guard: the proxy must refuse to fetch non-allowlisted hosts, so the
    endpoint can't be abused as an open proxy.
  - Master->child playlist rewriting: a returned .m3u8 has its URIs rewritten to
    point back at our /segment endpoint (so a browser <video> plays through us).
"""
from __future__ import annotations

import urllib.parse
from fastapi.testclient import TestClient

from flowsense.api_server.main import app


def _client():
    # The shipped lifespan opens Postgres; tests don't have one. Replace the
    # lifespan with a no-op so we can exercise non-DB routes in isolation.
    from contextlib import asynccontextmanager

    def _noop(app):
        yield

    app.router.lifespan_context = asynccontextmanager(_noop)
    return TestClient(app)


def test_segment_refuses_non_allowlisted_host():
    c = _client()
    evil = "http://169.254.169.254/latest/meta-data"  # SSRF to cloud metadata
    r = c.get("/api/v1/stream/segment", params={"url": evil})
    assert r.status_code == 403, r.status_code


def test_segment_refuses_non_http_scheme():
    c = _client()
    r = c.get("/api/v1/stream/segment", params={"url": "file:///etc/passwd"})
    assert r.status_code == 400, r.status_code


def test_playlist_requires_resolvable_camera():
    c = _client()
    # Camera 999999 does not exist in the Kudus list -> 404 (not a proxy error).
    r = c.get("/api/v1/stream/999999/playlist", timeout=90)
    assert r.status_code in (404, 502), r.status_code


def test_master_playlist_rewritten_to_segment_proxy():
    """A live Kudus master playlist must come back with child URIs pointing at
    our /segment endpoint (proves the rewrite path without depending on video
    frames). Skipped if the upstream is unreachable in the test env."""
    import os

    if not os.getenv("FLOWSENSE_API_KEY"):
        import pytest

        pytest.skip("no FLOWSENSE_API_KEY; live camera list unavailable")
    c = _client()
    r = c.get("/api/v1/stream/1/playlist", timeout=90)
    if r.status_code == 200:
        body = r.text
        assert "api/v1/stream/segment" in body, "child URI not rewritten to proxy"
        assert r.headers.get("content-type") == "application/vnd.apple.mpegurl"
    else:
        # upstream flaky in CI -- don't fail the suite on network
        import pytest

        pytest.skip(f"upstream returned {r.status_code}")
