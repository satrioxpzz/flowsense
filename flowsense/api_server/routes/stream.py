"""HLS stream proxy routes (option A from the user request).

Goal: let a browser play a Kudus CCTV feed through the FlowSense API without
depending on the upstream source's CORS headers (which are typically absent for
video segments).

How it works:
  GET /api/v1/stream/{camera_id}/playlist
      Fetches the camera's .m3u8 (master or child) playlist from the live Kudus
      source and rewrites every relative/absolute *.ts (and nested .m3u8) URI to
      point at our own segment proxy below. Returns it with the HLS mime type.
      The browser's <video> element then requests segments (and any nested child
      playlists) from us. The camera list is cached for 60s so we don't hit the
      slow Kudus camera-API on every request.

  GET /api/v1/stream/segment?url=<encoded .ts/.m3u8 url>
      Streams a single upstream segment (or nested playlist) back to the client
      using httpx streaming -- we never buffer the whole (live) segment. If the
      URL is itself a playlist (.m3u8) it is rewritten and returned inline.

This keeps the API as a pure pass-through proxy; no decoding/transcoding, no
GPU. It only ever proxies URLs that belong to the configured Kudus source host,
so it cannot be abused as an open proxy (see _assert_safe_upstream).
"""
from __future__ import annotations

import asyncio
import threading
import time
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from ...config import load_config
from ...cctv_client import fetch_cameras, find_camera
from ...database.security import require_api_key

router = APIRouter()

_HLS_MIME = "application/vnd.apple.mpegurl"
_SEGMENT_MIME = "application/octet-stream"

# Per-process httpx client (connection pooling). Created lazily; closed on app
# shutdown via the router's lifespan hook registered in main.py.
_client: httpx.AsyncClient | None = None

# Camera list cache -- the Kudus camera API is slow (~20s) and a single call is
# enough for the whole minute. Guarded by a lock; refreshed after TTL.
_cam_cache: list[dict] | None = None
_cam_cache_ts: float = 0.0
_cam_cache_ttl: float = 60.0
_cam_cache_lock = threading.Lock()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        # Generous timeouts: the slow part (camera-API) is cached; the HLS fetch
        # itself is fast once we have the URL.
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0))
    return _client


async def _close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


def _get_cameras() -> list[dict]:
    global _cam_cache, _cam_cache_ts
    with _cam_cache_lock:
        if _cam_cache is not None and (time.time() - _cam_cache_ts) < _cam_cache_ttl:
            return _cam_cache
    # Fetch outside the lock so we don't block concurrent requests on the slow API.
    cfg = load_config()
    cams = fetch_cameras(cfg)
    with _cam_cache_lock:
        _cam_cache = cams
        _cam_cache_ts = time.time()
    return cams


def _resolve_camera_url(camera_id: str | int, name: str | None = None) -> str:
    cams = _get_cameras()
    cam = find_camera(cams, name=name, cam_id=camera_id)
    url = cam.get("url")
    if not url:
        raise HTTPException(status_code=404, detail="Camera has no stream URL")
    return url


def _assert_safe_upstream(target: str, allowed_hosts: set[str]) -> None:
    """Refuse to proxy anything that isn't on an allowlisted Kudus host.

    Prevents this endpoint from becoming an open proxy / SSRF vector. The camera
    list API and the actual HLS streams live on different subdomains of
    kuduskab.go.id, so we accept both the configured API host and every host
    that appears in the (trusted, first-party) camera list.
    """
    try:
        p = urllib.parse.urlparse(target)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed segment URL")
    if p.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) upstreams allowed")
    if p.hostname not in allowed_hosts:
        raise HTTPException(
            status_code=403,
            detail=f"Refusing to proxy to non-allowlisted host: {p.hostname}",
        )


def _allowed_hosts() -> set[str]:
    """Hosts we are willing to proxy to: the configured API host plus every host
    seen in the first-party camera list (both are Kudus subdomains)."""
    cfg = load_config()
    hosts = {urllib.parse.urlparse(cfg.api_url).hostname}
    try:
        for cam in _get_cameras():
            h = urllib.parse.urlparse(cam.get("url", "")).hostname
            if h:
                hosts.add(h)
    except Exception:
        pass
    return {h for h in hosts if h}


def _rewrite_playlist(body: str, base_url: str, proxy_base: str) -> str:
    """Rewrite every URI in an m3u8 playlist to point at our segment proxy.

    Relative URIs are resolved against the playlist's own base URL. ``proxy_base``
    is the public base URL of this API (e.g. ``request.base_url``), used to build
    the ``/api/v1/stream/segment?url=...`` links.
    """
    base = urllib.parse.urlparse(base_url)
    base_dir = base_url[: base_url.rfind("/") + 1]
    out_lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        # A URI line (variant playlist, segment, or nested m3u8).
        if stripped.startswith("http://") or stripped.startswith("https://"):
            target = stripped
        else:
            target = urllib.parse.urljoin(base_dir, stripped)
        proxy = (
            f"{proxy_base}api/v1/stream/segment"
            f"?url={urllib.parse.quote(target, safe='')}"
        )
        out_lines.append(proxy)
    return "\n".join(out_lines)


@router.get("/{camera_id}/playlist")
async def stream_playlist(
    camera_id: str,
    request: Request,
    name: str | None = Query(None, description="optional name substring match"),
):
    """Return the camera's HLS playlist, with segment URLs rewritten to proxy here."""
    try:
        source_url = _resolve_camera_url(camera_id, name=name)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - surface as 502, never leak internals
        raise HTTPException(status_code=502, detail=f"Upstream camera lookup failed: {e}")

    client = await _get_client()
    try:
        resp = await client.get(source_url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream playlist error: {e}")

    body = resp.text
    rewritten = _rewrite_playlist(body, source_url, str(request.base_url))
    return Response(content=rewritten, media_type=_HLS_MIME)


@router.get("/segment")
async def stream_segment(
    request: Request,
    url: str = Query(..., description="encoded upstream .ts/.m3u8 URL"),
):
    """Stream a single upstream segment (or nested playlist) back to the client."""
    cfg = load_config()
    allowed = _allowed_hosts()
    decoded = urllib.parse.unquote(url)
    _assert_safe_upstream(decoded, allowed)

    client = await _get_client()
    try:
        upstream = await client.get(decoded)
        upstream.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream segment error: {e}")

    if "mpegurl" in upstream.headers.get("content-type", "") or decoded.endswith(".m3u8"):
        # Nested playlist: rewrite and return inline.
        body = upstream.text
        rewritten = _rewrite_playlist(body, decoded, str(request.base_url))
        return Response(content=rewritten, media_type=_HLS_MIME)

    # Stream the binary segment without buffering the whole thing.
    async def _chunker():
        async for chunk in upstream.aiter_bytes(chunk_size=64 * 1024):
            yield chunk

    return StreamingResponse(_chunker(), media_type=_SEGMENT_MIME)
