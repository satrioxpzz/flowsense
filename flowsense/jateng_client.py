"""Jateng public CCTV portal client (token-free, read-only).

This module ingests the camera list published on the PUBLIC Jateng CCTV portal
(gis.perhubungan.jatengprov.go.id/cctv). The portal hardcodes its camera array
(`cctvData`) in client-side JavaScript, which is freely readable by any visitor.
We only parse that already-public metadata (name, region, GPS, stream URL). We do
NOT use any leaked credentials (e.g. the Karanganyar ZoneMinder token) and we do
NOT download video frames here.

Caveat: the `hls_url` values in the public array are mostly web-portal pages
(HTML), not raw `.m3u8` manifests. Real HLS manifests usually sit behind those
pages. Callers should treat `hls_url` as a "portal/landing URL" and verify the
actual stream endpoint before ingestion.

Security: any entry whose URL embeds a static auth token (e.g. ZoneMinder
`nph-zms?auth=...`) is **skipped** — such tokens are leaked credentials in the
public source and must never be stored or replayed by FlowSense.
"""
from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from typing import List, Optional

import requests

# Public, unauthenticated portal page. No API key or token required.
JATENG_CCTV_PORTAL = "https://gis.perhubungan.jatengprov.go.id/cctv"

# Some hosts present invalid cert chains from this client; we do not send
# secrets, so a relaxed TLS context is acceptable for a public, read-only GET.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_HEADERS = {"User-Agent": "FlowSense/ingest (+https://github.com/flowsense)"}

# How many times to retry the portal fetch.
_DEFAULT_RETRIES = 3
_DEFAULT_TIMEOUT = 25.0


@dataclass(frozen=True)
class JatengCamera:
    idx: int
    name: str
    region: str
    latitude: Optional[float]
    longitude: Optional[float]
    portal_url: str
    host: str

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def _parse_cctv_data(html: str) -> List[dict]:
    """Extract the cctvData array fields via line-based regex.

    The embedded array is brace-unbalanced in the live page source, so we pull
    each field independently rather than parsing the JS object.
    """
    lokasi = re.findall(r"lokasi\s*:\s*'([^']*)'", html)
    hls = re.findall(r"hls_url\s*:\s*'([^']*)'", html)
    lat = re.findall(r"latitude\s*:\s*(-?\d+\.\d+)", html)
    lng = re.findall(r"longitude\s*:\s*(-?\d+\.\d+)", html)
    wil = re.findall(r"wilayah\s*:\s*'([^']*)'", html)
    n = max(len(lokasi), len(hls), len(lat))
    out: List[dict] = []
    for i in range(n):
        out.append({
            "name": lokasi[i] if i < len(lokasi) else None,
            "region": wil[i] if i < len(wil) else None,
            "latitude": float(lat[i]) if i < len(lat) else None,
            "longitude": float(lng[i]) if i < len(lng) else None,
            "portal_url": hls[i] if i < len(hls) else None,
        })
    return out


def fetch_jateng_cameras(
    portal_url: str = JATENG_CCTV_PORTAL,
    retries: int = _DEFAULT_RETRIES,
    timeout: float = _DEFAULT_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> List[JatengCamera]:
    """Fetch the public Jateng camera list (no auth, no token).

    Returns normalized JatengCamera objects. Raises RuntimeError after retries.
    """
    import urllib.parse as up

    client = session if session is not None else requests
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            r = client.get(
                portal_url,
                headers=_HEADERS,
                timeout=timeout,
                verify=False,  # public page; no secrets transmitted
            )
            r.raise_for_status()
            rows = _parse_cctv_data(r.text)
            cams: List[JatengCamera] = []
            for i, row in enumerate(rows, start=1):
                url = row.get("portal_url") or ""
                # SECURITY: never ingest URLs that embed a static auth token
                # (e.g. ZoneMinder nph-zms ?auth=...). Such tokens are leaked
                # credentials in the public source and must not be stored or
                # replayed by FlowSense. Skip them silently.
                if "auth=" in url or "nph-zms" in url:
                    continue
                cams.append(JatengCamera(
                    idx=i,
                    name=row.get("name") or f"cam-{i}",
                    region=row.get("region") or "",
                    latitude=row.get("latitude"),
                    longitude=row.get("longitude"),
                    portal_url=url,
                    host=up.urlparse(url).netloc if url else "",
                ))
            return cams
        except (requests.RequestException, ValueError, OSError) as e:
            last_err = e
            if attempt < retries - 1:
                import time
                time.sleep(2.0 * (2 ** attempt))
    raise RuntimeError(f"fetch_jateng_cameras failed after {retries} attempts: {last_err}")


def find_jateng_camera(
    cameras: List[JatengCamera],
    name: Optional[str] = None,
    idx: Optional[int] = None,
    host: Optional[str] = None,
) -> JatengCamera:
    if idx is not None:
        for c in cameras:
            if c.idx == int(idx):
                return c
        raise RuntimeError(f"No Jateng camera with idx={idx}")
    if name:
        low = name.lower()
        for c in cameras:
            if low in (c.name or "").lower():
                return c
        raise RuntimeError(f"No Jateng camera matching name={name!r}")
    if host:
        low = host.lower()
        for c in cameras:
            if low in (c.host or "").lower():
                return c
        raise RuntimeError(f"No Jateng camera with host={host!r}")
    raise RuntimeError("Provide a name, idx, or host to find a camera")
