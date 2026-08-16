"""Kudus CCTV camera API client with retry/backoff."""
import time
from typing import List, Optional

import requests

from .config import Config


def fetch_cameras(cfg: Config, session=None) -> List[dict]:
    """Fetch the camera list, retrying with exponential backoff."""
    client = session if session is not None else requests
    last_err = None
    for attempt in range(cfg.api_retries):
        try:
            r = client.get(
                cfg.api_url,
                headers={"X-SDC": cfg.api_key},
                timeout=cfg.api_timeout,
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"API failed: {data}")
            return data["camera"]
        except (requests.RequestException, ValueError, OSError) as e:
            last_err = e
            if attempt < cfg.api_retries - 1:
                time.sleep(cfg.api_backoff * (2 ** attempt))
    raise RuntimeError(f"fetch_cameras failed after {cfg.api_retries} attempts: {last_err}")


def find_camera(cameras, name: Optional[str] = None, cam_id=None) -> dict:
    if cam_id is not None:
        for c in cameras:
            if str(c["id"]) == str(cam_id):
                return c
        raise RuntimeError(f"No camera with id={cam_id}")
    if name:
        low = name.lower()
        for c in cameras:
            if low in c.get("nama", "").lower():
                return c
        raise RuntimeError(f"No camera matching name={name!r}")
    raise RuntimeError("Provide a camera name or id")
