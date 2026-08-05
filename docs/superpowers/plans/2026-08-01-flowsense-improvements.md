# FlowSense Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden FlowSense into a testable, maintainable, reliable connector: secrets moved to env, resilient stream/API handling, per-vehicle lane-crossing counting via YOLO tracking, **per-lane density classification (klasifikasi kepadatan)**, structured logging, and full unit test coverage — without breaking the existing `connector.py` CLI or the `.jsonl` record schema. This plan implements the edge side of the system shown in `Reference/FlowSense_Diagram.drawio` (layers 1–3: SOURCE, PROCESSING, and the connector's record/snapshot outputs); downstream layers 3→6 are scoped as a roadmap (see end).

**Architecture:** Extract the monolithic `connector.py` into a `flowsense/` package with focused modules (`config`, `api`, `lanes`, `detector`, `density`, `stream`, `telemetry`, `runner`). `connector.py` stays as a thin entry point so existing usage (`python connector.py --camera ...`) keeps working. All pure logic (lane mapping, summarization, tracking, density classification, config parsing) is unit-tested offline; streaming/API code is tested with injected fakes. No real network or camera streams are touched by tests.

**Tech Stack:** Python 3.13, OpenCV (cv2), numpy, requests, ultralytics (YOLOv11), pytest.

## System Context (from `Reference/FlowSense_Diagram.drawio`)

The reference diagram is the canonical system architecture. This plan implements the **edge connector** (diagram layers 1–3, left half). Each layer maps to plan tasks as follows:

| Diagram layer | Meaning | Covered by plan tasks |
|---|---|---|
| 1. SOURCE | Portal CCTV Pemkab Kudus (HLS) — "Tarik frame" | `connector.py` / `runner.main` (Task 9) opens the HLS stream via `ReconnectingStream` (Task 8) |
| 2. PROCESSING | Python + OpenCV + YOLOv11 — "hitung per ROI → klasifikasi kepadatan" | ROI count + lane mapping (Task 3), YOLO wrapper + summarization (Task 6), lane-crossing tracking (Task 7), **density classification (Task 12)** |
| 3. DATABASE | PostgreSQL + TimescaleDB (Record JSON) | Connector emits the `.jsonl` record (schema in Task 9/11); DB ingestion is downstream (roadmap) |
| 3b. STORAGE | Garage/disk (Snapshot JPEG) | Snapshot produced in `--snapshot-only` calibration (Task 9); persistent snapshot sink is downstream (roadmap) |
| 4. API/BACKEND | FastAPI + JWT (operator) | Not in this plan — roadmap |
| 5. CLIENT | Flutter / Riverpod / flutter_map (warga + operator flavors) | Not in this plan — roadmap |
| 5/6. SIMULATION | SUMO + TraCI (input: lane counts from layer 3; output: wait-time delta) | Consumes connector's per-lane counts — roadmap; reference at `Reference/sumo-adaptive-traffic-signal-control-main` |

**Constraints preserved from the diagram:** the connector outputs *two* artifacts — a **Record JSON** (to layer 3 DATABASE) and a **Snapshot JPEG** (to layer 3b STORAGE). The plan's record schema is the contract those downstream layers consume.

## Global Constraints

- **No new dependencies.** Keep `requirements.txt` as-is (`ultralytics`, `opencv-python`, `numpy`, `requests`). The `.env` loader must be stdlib-only.
- **ultralytics is NOT installed** in the current environment. `flowsense/detector.py` must import ultralytics lazily inside functions so `pytest` runs without it.
- **Tests never touch the network or a camera.** Stream/API code gets fake objects via injection or `monkeypatch`.
- **CLI compatibility:** `python connector.py --camera "Simpang DPRD Arah Kota"`, `--camera-id`, `--url`, `--out`, `--snapshot-only`, `--show`, `--skip-detect` must all keep working.
- **Record schema:** every emitted `.jsonl` record keeps `ts`, `camera_id`, `camera`, `total_vehicles`, `per_lane`. Tracking mode adds an optional `crossings` field. Existing keys never removed or renamed.
- **API key:** the hardcoded key must be removed from source. It is read from env var `FLOWSENSE_API_KEY` or a local `.env` file. `.env` is gitignored.
- Run all tests with `python -m pytest -q` from the project root (`C:\Users\legion\flowsense`). `python -m pytest` puts the CWD on `sys.path`, so `import flowsense` resolves.
- Commit after every task. Repo has 1 commit and no remote; all work happens on the current branch.

---

### Task 1: Package skeleton + repo hygiene

**Files:**
- Create: `flowsense/__init__.py`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: importable `flowsense` package; gitignore rules; env template. Later tasks fill package modules.

- [x] **Step 1: Create the package directory and `__init__.py`**

Create `flowsense/__init__.py` with:

```python
"""FlowSense - edge vehicle detection for Kudus CCTV streams."""
__version__ = "0.2.0"
```

- [x] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
.env
data/*.jsonl
data/frame_test.jpg
```

- [x] **Step 3: Create `.env.example`**

```
# Copy this file to .env and fill in the real values.
# .env is gitignored - never commit real secrets.
FLOWSENSE_API_KEY=
FLOWSENSE_API_URL=https://kudussehat.kuduskab.go.id/api/get-cctv
FLOWSENSE_API_TIMEOUT=25
FLOWSENSE_API_RETRIES=3
FLOWSENSE_API_BACKOFF=2
FLOWSENSE_MIN_CONF=0.35
FLOWSENSE_INTERVAL=2
FLOWSENSE_MODEL=yolo11n.pt
```

- [x] **Step 4: Write the smoke test**

Create `tests/test_smoke.py`:

```python
def test_package_imports():
    import flowsense

    assert flowsense.__name__ == "flowsense"
    assert hasattr(flowsense, "__version__")
```

- [x] **Step 5: Run the test**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: 1 passed.

- [x] **Step 6: Verify `.env` is ignored**

Run: `git check-ignore .env`
Expected: `.env` is printed (proves the gitignore rule works).

- [x] **Step 7: Commit**

```bash
git add flowsense/__init__.py .gitignore .env.example tests/test_smoke.py
git commit -m "chore: add flowsense package skeleton, gitignore, and env template"
```

---

### Task 2: Config module (secrets moved to env)

**Files:**
- Create: `flowsense/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces: `Config` frozen dataclass with fields `api_url: str`, `api_key: str`, `api_timeout: float`, `api_retries: int`, `api_backoff: float`, `min_conf: float`, `interval: float`, `model_path: str`, `base_dir: Path`, plus properties `rois_path: Path` and `data_dir: Path`; function `load_config(env_path: Path = DEFAULT_ENV_PATH) -> Config`. Env vars are `FLOWSENSE_API_KEY`, `FLOWSENSE_API_URL`, `FLOWSENSE_API_TIMEOUT`, `FLOWSENSE_API_RETRIES`, `FLOWSENSE_API_BACKOFF`, `FLOWSENSE_MIN_CONF`, `FLOWSENSE_INTERVAL`, `FLOWSENSE_MODEL`. Real environment variables take precedence over `.env` values.

- [x] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
from flowsense.config import Config, load_config


def test_defaults(tmp_path):
    cfg = load_config(env_path=tmp_path / "missing.env")
    assert cfg.api_key == ""
    assert cfg.api_url == "https://kudussehat.kuduskab.go.id/api/get-cctv"
    assert cfg.interval == 2.0
    assert cfg.min_conf == 0.35
    assert cfg.rois_path.name == "rois.json"
    assert cfg.data_dir.name == "data"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOWSENSE_API_KEY", "env-secret")
    monkeypatch.setenv("FLOWSENSE_INTERVAL", "5.5")
    cfg = load_config(env_path=tmp_path / "missing.env")
    assert cfg.api_key == "env-secret"
    assert cfg.interval == 5.5


def test_dotenv_loaded_when_env_unset(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        'FLOWSENSE_API_KEY=dot-secret\nFLOWSENSE_INTERVAL=7\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("FLOWSENSE_API_KEY", raising=False)
    monkeypatch.delenv("FLOWSENSE_INTERVAL", raising=False)
    cfg = load_config(env_path=env)
    assert cfg.api_key == "dot-secret"
    assert cfg.interval == 7.0


def test_env_beats_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('FLOWSENSE_API_KEY=dot-secret\n', encoding="utf-8")
    monkeypatch.setenv("FLOWSENSE_API_KEY", "real-secret")
    cfg = load_config(env_path=env)
    assert cfg.api_key == "real-secret"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.config'`.

- [x] **Step 3: Implement the minimal module**

Create `flowsense/config.py`:

```python
"""FlowSense configuration loaded from environment variables and .env."""
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv(path: Path) -> None:
    """Tiny stdlib .env loader: KEY=VALUE lines, no interpolation."""
    if not Path(path).exists():
        return
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    api_url: str = "https://kudussehat.kuduskab.go.id/api/get-cctv"
    api_key: str = ""
    api_timeout: float = 25.0
    api_retries: int = 3
    api_backoff: float = 2.0
    min_conf: float = 0.35
    interval: float = 2.0
    model_path: str = "yolo11n.pt"
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def rois_path(self) -> Path:
        return self.base_dir / "config" / "rois.json"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"


def load_config(env_path: Path = DEFAULT_ENV_PATH) -> Config:
    _load_dotenv(env_path)
    defaults = Config()
    return Config(
        api_url=os.environ.get("FLOWSENSE_API_URL", defaults.api_url),
        api_key=os.environ.get("FLOWSENSE_API_KEY", defaults.api_key),
        api_timeout=float(os.environ.get("FLOWSENSE_API_TIMEOUT", defaults.api_timeout)),
        api_retries=int(os.environ.get("FLOWSENSE_API_RETRIES", defaults.api_retries)),
        api_backoff=float(os.environ.get("FLOWSENSE_API_BACKOFF", defaults.api_backoff)),
        min_conf=float(os.environ.get("FLOWSENSE_MIN_CONF", defaults.min_conf)),
        interval=float(os.environ.get("FLOWSENSE_INTERVAL", defaults.interval)),
        model_path=os.environ.get("FLOWSENSE_MODEL", defaults.model_path),
    )
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: 4 passed.

- [x] **Step 5: Commit**

```bash
git add flowsense/config.py tests/test_config.py
git commit -m "feat: add env/.env config module and move API key out of source"
```

---

### Task 3: Lanes module (ROI loading + lane mapping)

**Files:**
- Create: `flowsense/lanes.py`
- Create: `tests/test_lanes.py`

**Interfaces:**
- Consumes: nothing (uses cv2, numpy, stdlib).
- Produces:
  - `load_rois(rois_path: Path, camera_key: str) -> dict` — returns `{lane_name: [[x, y], ...]}` or `{}` if file missing/unknown key.
  - `point_in_poly(pt: tuple, poly: list) -> bool` — True if `pt` is on/inside `poly`.
  - `lane_from_detection(bbox: list[float], lanes: dict) -> str | None` — bottom-center of `bbox` (`[x1, y1, x2, y2]`) mapped to the containing lane, else `None`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_lanes.py`:

```python
import json

from flowsense.lanes import lane_from_detection, load_rois, point_in_poly

SQUARE = [(0, 0), (100, 0), (100, 100), (0, 100)]


def test_point_in_poly():
    assert point_in_poly((50, 50), SQUARE)
    assert not point_in_poly((200, 200), SQUARE)


def test_point_on_edge_counts_as_inside():
    assert point_in_poly((0, 50), SQUARE)


def test_lane_from_detection():
    lanes = {
        "kota": [(0, 0), (100, 0), (100, 100), (0, 100)],
        "ploso": [(200, 0), (300, 0), (300, 100), (200, 100)],
    }
    assert lane_from_detection([10, 20, 30, 40], lanes) == "kota"
    assert lane_from_detection([250, 20, 270, 90], lanes) == "ploso"
    assert lane_from_detection([500, 20, 520, 90], lanes) is None


def test_load_rois_missing_file(tmp_path):
    assert load_rois(tmp_path / "nope.json", "30") == {}


def test_load_rois_unknown_camera(tmp_path):
    p = tmp_path / "rois.json"
    p.write_text(json.dumps({"30": {"kota": [[0, 0], [1, 0], [1, 1]]}}), encoding="utf-8")
    assert load_rois(p, "99") == {}


def test_load_rois_known_camera(tmp_path):
    p = tmp_path / "rois.json"
    p.write_text(json.dumps({"30": {"kota": [[0, 0], [1, 0], [1, 1]]}}), encoding="utf-8")
    assert load_rois(p, "30") == {"kota": [[0, 0], [1, 0], [1, 1]]}
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_lanes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.lanes'`.

- [x] **Step 3: Implement the minimal module**

Create `flowsense/lanes.py`:

```python
"""Lane ROI loading and ground-point mapping."""
import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def load_rois(rois_path, camera_key: str) -> dict:
    path = Path(rois_path)
    if not path.exists():
        return {}
    rois = json.loads(path.read_text(encoding="utf-8"))
    return rois.get(camera_key, {})


def point_in_poly(pt, poly) -> bool:
    return cv2.pointPolygonTest(np.array(poly, np.int32), pt, False) >= 0


def lane_from_detection(bbox, lanes) -> Optional[str]:
    """Map a detection to the lane containing its ground point (bbox bottom-center)."""
    bx1, _, bx2, by2 = bbox
    ground = ((bx1 + bx2) / 2.0, by2)
    for lane_name, poly in lanes.items():
        if point_in_poly(ground, poly):
            return lane_name
    return None
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_lanes.py -v`
Expected: 6 passed.

- [x] **Step 5: Commit**

```bash
git add flowsense/lanes.py tests/test_lanes.py
git commit -m "feat: extract lane ROI loading and lane mapping into flowsense.lanes"
```

---

### Task 4: API client (retry/backoff, injectable session)

**Files:**
- Create: `flowsense/api.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: `Config` (fields `api_url`, `api_key`, `api_timeout`, `api_retries`, `api_backoff`).
- Produces:
  - `fetch_cameras(cfg: Config, session=None) -> list[dict]` — GET `cfg.api_url` with header `X-SDC: cfg.api_key`; validates `data["success"]`; retries up to `cfg.api_retries` with exponential backoff `backoff * 2**attempt`; raises `RuntimeError` when exhausted. `session` must expose `get(url, **kwargs)`; defaults to the `requests` module.
  - `find_camera(cameras: list[dict], name: str | None = None, cam_id: int | str | None = None) -> dict` — by id or case-insensitive name substring; raises `RuntimeError` on no match; raises if neither given.

- [x] **Step 1: Write the failing tests**

Create `tests/test_api.py`:

```python
import pytest
import requests

from flowsense.api import fetch_cameras, find_camera
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
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.api'`.

- [x] **Step 3: Implement the minimal module**

Create `flowsense/api.py`:

```python
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
        except (requests.RequestException, RuntimeError, ValueError) as e:
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: 6 passed.

- [x] **Step 5: Commit**

```bash
git add flowsense/api.py tests/test_api.py
git commit -m "feat: add retrying Kudus API client with injectable session"
```

---

### Task 5: Telemetry module (structured JSON logging)

**Files:**
- Create: `flowsense/telemetry.py`
- Create: `tests/test_telemetry.py`

**Interfaces:**
- Consumes: stdlib `logging`, `json`, `sys`.
- Produces:
  - `setup_logging(level: str = "INFO", json_output: bool = True) -> logging.Logger` — returns the `"flowsense"` logger with a single stdout handler (idempotent).
  - `JsonFormatter(logging.Formatter)` — one JSON object per line with keys `ts`, `level`, `logger`, `msg`, plus any of `camera_id`, `camera`, `lane`, `event`, `frame`, `url`, `attempt` set as `LogRecord` attributes, plus `exc` when exceptions are logged.

- [x] **Step 1: Write the failing tests**

Create `tests/test_telemetry.py`:

```python
import json
import logging

from flowsense.telemetry import JsonFormatter, setup_logging


def test_json_formatter_serializes_extra_fields():
    record = logging.LogRecord("flowsense", logging.INFO, "file.py", 1, "reconnecting", None, None)
    record.camera_id = 30
    record.attempt = 2
    data = json.loads(JsonFormatter().format(record))
    assert data["msg"] == "reconnecting"
    assert data["camera_id"] == 30
    assert data["attempt"] == 2
    assert data["level"] == "INFO"


def test_setup_logging_returns_flowsense_logger():
    logger = setup_logging("DEBUG", json_output=True)
    assert logger.name == "flowsense"
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1


def test_setup_logging_is_idempotent():
    setup_logging()
    logger = setup_logging()
    assert len(logger.handlers) == 1
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_telemetry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.telemetry'`.

- [x] **Step 3: Implement the minimal module**

Create `flowsense/telemetry.py`:

```python
"""Structured JSON logging for FlowSense."""
import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    EXTRA_FIELDS = ("camera_id", "camera", "lane", "event", "frame", "url", "attempt")

    def format(self, record):
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in self.EXTRA_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def setup_logging(level: str = "INFO", json_output: bool = True) -> logging.Logger:
    logger = logging.getLogger("flowsense")
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter() if json_output else logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_telemetry.py -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add flowsense/telemetry.py tests/test_telemetry.py
git commit -m "feat: add structured JSON logging via flowsense.telemetry"
```

---

### Task 6: Detector module (YOLO wrapper + frame summarization)

**Files:**
- Create: `flowsense/detector.py`
- Create: `tests/test_detector.py`

**Interfaces:**
- Consumes: `lane_from_detection(bbox, lanes)` from `flowsense.lanes` (Task 3).
- Produces:
  - `VEHICLE_CLASSES: dict[int, str]` — `{1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}`.
  - `load_model(model_path: str)` — lazily imports ultralytics and returns `YOLO(model_path)`. **Must not be imported at module load.**
  - `summarize_frame(results, lanes, min_conf: float = 0.35) -> dict` — returns `{"total_vehicles": int, "per_lane": dict[str, int], "vehicles": list[dict]}`. Each vehicle dict: `{"bbox", "cls", "type", "conf", "lane"}`. Filters non-vehicle classes and `conf < min_conf`.
  - `track_summary(results, lanes, min_conf: float = 0.35) -> tuple[list[dict], list[tuple[int, str]]]` — same vehicle dicts plus `"track_id"`, and returns `(dets, [(track_id, lane)])` pairs for tracked boxes only (`box.id is not None`).

- [x] **Step 1: Write the failing tests**

Create `tests/test_detector.py`:

```python
from flowsense.detector import summarize_frame, track_summary


class FakeBox:
    def __init__(self, cls, conf, xyxy, tid=None):
        self.cls = [cls]
        self.conf = [conf]
        self.xyxy = [xyxy]
        self.id = None if tid is None else [tid]


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


def _results(boxes):
    return [FakeResult(boxes)]


def test_summarize_counts_vehicles_only():
    lanes = {"kota": [(0, 0), (500, 0), (500, 500), (0, 500)]}
    boxes = [
        FakeBox(2, 0.9, [10, 10, 50, 90]),    # car -> in lane
        FakeBox(3, 0.4, [60, 10, 80, 80]),    # motorcycle -> in lane
        FakeBox(0, 0.9, [100, 100, 120, 120]),  # person -> ignored
    ]
    s = summarize_frame(_results(boxes), lanes, min_conf=0.35)
    assert s["total_vehicles"] == 2
    assert s["per_lane"] == {"kota": 2}
    assert s["vehicles"][0]["type"] == "car"


def test_summarize_filters_low_conf():
    s = summarize_frame(_results([FakeBox(2, 0.2, [10, 10, 50, 90])]), {}, min_conf=0.35)
    assert s["total_vehicles"] == 0


def test_summarize_unknown_lane_is_none():
    lanes = {"kota": [(0, 0), (100, 0), (100, 100), (0, 100)]}
    s = summarize_frame(_results([FakeBox(2, 0.9, [500, 500, 550, 590])]), lanes, min_conf=0.35)
    assert s["total_vehicles"] == 1
    assert s["vehicles"][0]["lane"] is None
    assert s["per_lane"] == {"kota": 0}


def test_track_summary_emits_pairs():
    lanes = {"kota": [(0, 0), (500, 0), (500, 500), (0, 500)]}
    boxes = [
        FakeBox(2, 0.9, [10, 10, 50, 90], tid=1),
        FakeBox(3, 0.5, [200, 10, 220, 80], tid=2),
        FakeBox(2, 0.9, [500, 500, 550, 590], tid=3),  # outside lanes -> lane None
    ]
    dets, pairs = track_summary(_results(boxes), lanes, min_conf=0.35)
    assert pairs == [(1, "kota"), (2, "kota"), (3, None)]
    assert dets[0]["track_id"] == 1
    assert dets[2]["lane"] is None
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.detector'`.

- [x] **Step 3: Implement the minimal module**

Create `flowsense/detector.py`:

```python
"""YOLO detection wrapper and frame summarization."""
from typing import List, Optional, Tuple

from .lanes import lane_from_detection

VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def load_model(model_path: str):
    """Lazy ultralytics import so unit tests run without it installed."""
    from ultralytics import YOLO

    return YOLO(model_path)


def _detections(results, min_conf):
    """Yield (cls, conf, bbox) for vehicle boxes above min_conf."""
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls not in VEHICLE_CLASSES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            yield cls, conf, [float(x) for x in box.xyxy[0].tolist()]


def summarize_frame(results, lanes, min_conf: float = 0.35) -> dict:
    counts = {name: 0 for name in lanes}
    vehicles = []
    for cls, conf, bbox in _detections(results, min_conf):
        det = {
            "bbox": bbox,
            "cls": cls,
            "type": VEHICLE_CLASSES[cls],
            "conf": conf,
            "lane": lane_from_detection(bbox, lanes),
        }
        vehicles.append(det)
        if det["lane"]:
            counts[det["lane"]] += 1
    return {
        "total_vehicles": len(vehicles),
        "per_lane": counts,
        "vehicles": vehicles,
    }


def track_summary(results, lanes, min_conf: float = 0.35) -> Tuple[List[dict], List[Tuple[int, Optional[str]]]]:
    """Tracked-mode summarization. Returns (dets, [(track_id, lane)]) pairs."""
    dets = []
    pairs = []
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls not in VEHICLE_CLASSES:
                continue
            conf = float(box.conf[0])
            if conf < min_conf:
                continue
            bbox = [float(x) for x in box.xyxy[0].tolist()]
            lane = lane_from_detection(bbox, lanes)
            det = {
                "bbox": bbox,
                "cls": cls,
                "type": VEHICLE_CLASSES[cls],
                "conf": conf,
                "lane": lane,
            }
            tid = int(box.id[0]) if box.id is not None else None
            if tid is not None:
                det["track_id"] = tid
                pairs.append((tid, lane))
            dets.append(det)
    return dets, pairs
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_detector.py -v`
Expected: 4 passed (3 summarize + 1 track).

- [x] **Step 5: Verify ultralytics stays lazy**

Run: `python -c "import flowsense.detector; print('no-ultralytics-import-ok')"`
Expected: prints `no-ultralytics-import-ok` (no `ModuleNotFoundError` even though ultralytics isn't installed).

- [x] **Step 6: Commit**

```bash
git add flowsense/detector.py tests/test_detector.py
git commit -m "feat: extract YOLO detection and frame summarization into flowsense.detector"
```

---

### Task 7: TrackingCounter (per-vehicle lane crossings)

**Files:**
- Create: `flowsense/counter.py`
- Create: `tests/test_counter.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class TrackingCounter` with:
    - `__init__(self)`
    - `update(self, tracked_dets: list[tuple[int, str | None]]) -> dict[str, int]` — feeds `(track_id, lane)` pairs; returns cumulative `{lane: count}`; ignores `lane is None`; counts each `(track_id, lane)` once ever.
    - `snapshot(self) -> dict[str, int]` — current cumulative counts.
    - `reset(self)` — clears all state.

- [x] **Step 1: Write the failing tests**

Create `tests/test_counter.py`:

```python
from flowsense.counter import TrackingCounter


def test_counts_once_per_track_lane():
    c = TrackingCounter()
    assert c.update([(1, "kota"), (1, "kota"), (2, "kota")]) == {"kota": 2}
    assert c.update([(2, "kota")]) == {"kota": 2}


def test_track_crosses_two_lanes():
    c = TrackingCounter()
    c.update([(1, "kota"), (1, "ploso")])
    assert c.snapshot() == {"kota": 1, "ploso": 1}


def test_ignores_no_lane():
    c = TrackingCounter()
    assert c.update([(1, None)]) == {}


def test_reset_clears_state():
    c = TrackingCounter()
    c.update([(1, "kota")])
    c.reset()
    assert c.snapshot() == {}
    assert c.update([(1, "kota")]) == {"kota": 1}
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_counter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.counter'`.

- [x] **Step 3: Implement the minimal module**

Create `flowsense/counter.py`:

```python
"""Unique per-track, per-lane crossing counting."""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


class TrackingCounter:
    """Counts each tracked vehicle once per lane it crosses."""

    def __init__(self):
        self.crossings: Dict[str, int] = defaultdict(int)
        self._seen = set()

    def update(self, tracked_dets: List[Tuple[int, Optional[str]]]) -> Dict[str, int]:
        for track_id, lane in tracked_dets:
            if lane is None:
                continue
            key = (track_id, lane)
            if key not in self._seen:
                self._seen.add(key)
                self.crossings[lane] += 1
        return self.snapshot()

    def snapshot(self) -> Dict[str, int]:
        return dict(self.crossings)

    def reset(self):
        self.crossings = defaultdict(int)
        self._seen = set()
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_counter.py -v`
Expected: 4 passed.

- [x] **Step 5: Commit**

```bash
git add flowsense/counter.py tests/test_counter.py
git commit -m "feat: add TrackingCounter for unique lane-crossing counts"
```

---

### Task 8: ReconnectingStream (resilient stream reads)

**Files:**
- Create: `flowsense/stream.py`
- Create: `tests/test_stream.py`

**Interfaces:**
- Consumes: `cv2`, `time`.
- Produces:
  - `class ReconnectingStream`:
    - `__init__(self, url: str, max_reconnects: int = 5, backoff: float = 3.0)`
    - `open(self)` — creates `cv2.VideoCapture(url)`; raises `RuntimeError` if `isOpened()` is False.
    - `read(self) -> tuple[bool, frame | None]` — reads; on read failure reopens with `backoff` sleep up to `max_reconnects` times, then returns `(False, None)`.
    - `release(self)` — releases the underlying capture (idempotent).

- [x] **Step 1: Write the failing tests**

Create `tests/test_stream.py`:

```python
import numpy as np
import pytest

from flowsense.stream import ReconnectingStream


def test_open_failure_raises(monkeypatch):
    class FakeCap:
        def __init__(self, url):
            self.url = url

        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr("flowsense.stream.cv2.VideoCapture", FakeCap)
    s = ReconnectingStream("http://x")
    with pytest.raises(RuntimeError, match="Could not open stream"):
        s.open()


def test_stream_reconnects_and_recovers(monkeypatch):
    calls = {"n": 0}

    class FakeCap:
        def __init__(self, url):
            calls["n"] += 1
            self.fails = 0 if calls["n"] >= 3 else 1
            self.frame = np.zeros((10, 10, 3), dtype=np.uint8)

        def isOpened(self):
            return True

        def read(self):
            if self.fails > 0:
                self.fails -= 1
                return False, None
            return True, self.frame

        def release(self):
            pass

    monkeypatch.setattr("flowsense.stream.cv2.VideoCapture", FakeCap)
    s = ReconnectingStream("http://x", max_reconnects=5, backoff=0.0)
    ok, frame = s.read()
    assert ok is True
    assert frame is not None
    assert calls["n"] == 3


def test_stream_gives_up_after_max_reconnects(monkeypatch):
    calls = {"n": 0}

    class FakeCap:
        def __init__(self, url):
            calls["n"] += 1

        def isOpened(self):
            return True

        def read(self):
            return False, None

        def release(self):
            pass

    monkeypatch.setattr("flowsense.stream.cv2.VideoCapture", FakeCap)
    s = ReconnectingStream("http://x", max_reconnects=2, backoff=0.0)
    ok, frame = s.read()
    assert ok is False
    assert frame is None
    assert calls["n"] == 3  # initial open + 2 reconnects
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_stream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.stream'`.

- [x] **Step 3: Implement the minimal module**

Create `flowsense/stream.py`:

```python
"""Reconnecting OpenCV video stream wrapper."""
import time

import cv2


class ReconnectingStream:
    """Wraps cv2.VideoCapture; reopens on read failure with backoff."""

    def __init__(self, url: str, max_reconnects: int = 5, backoff: float = 3.0):
        self.url = url
        self.max_reconnects = max_reconnects
        self.backoff = backoff
        self._cap = None

    def open(self):
        cap = cv2.VideoCapture(self.url)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Could not open stream: {self.url}")
        self._cap = cap

    def read(self):
        if self._cap is None:
            self.open()
        attempt = 0
        while True:
            ok, frame = self._cap.read()
            if ok and frame is not None:
                return True, frame
            attempt += 1
            if attempt > self.max_reconnects:
                return False, None
            self._cap.release()
            self._cap = None
            time.sleep(self.backoff)
            self.open()

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_stream.py -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add flowsense/stream.py tests/test_stream.py
git commit -m "feat: add ReconnectingStream with backoff and bounded reconnect attempts"
```

---

### Task 9: Runner + rewrite connector.py to use the package

**Files:**
- Create: `flowsense/runner.py`
- Create: `flowsense/__main__.py`
- Rewrite: `connector.py` (replace entire file)
- Create: `tests/test_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 1-8 — `load_config`/`replace` (Config), `fetch_cameras`/`find_camera`, `load_rois`, `load_model`/`summarize_frame`/`track_summary`, `TrackingCounter`, `ReconnectingStream`, `setup_logging`, `JsonFormatter` extra fields.
- Produces:
  - `parse_args(argv=None) -> argparse.Namespace` — same flags as the old CLI plus `--track`, `--log-json` (default True), `--log-level` (default "INFO").
  - `build_record(ts: float, camera: dict, summary: dict, crossings: dict | None = None) -> dict` — record with `ts` (int), `camera_id`, `camera`, `total_vehicles`, `per_lane`; includes `crossings` only when not None.
  - `per_lane_present(dets: list[dict]) -> dict[str, int]` — present-count per lane for tracked mode.
  - `main(argv=None) -> int` — wires everything: config, logging, camera resolution, ROI load, model load, stream, emit loop with graceful `KeyboardInterrupt`, snapshot/`--show` support.

- [x] **Step 1: Write the failing tests**

Create `tests/test_runner.py`:

```python
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
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.runner'`.

- [x] **Step 3: Implement `flowsense/runner.py`**

```python
"""FlowSense runner: main loop, CLI, graceful shutdown."""
import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from .api import fetch_cameras, find_camera
from .config import load_config
from .counter import TrackingCounter
from .detector import load_model, summarize_frame, track_summary
from .lanes import load_rois
from .stream import ReconnectingStream
from .telemetry import setup_logging

log = logging.getLogger("flowsense")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="FlowSense edge connector")
    ap.add_argument("--camera", help="camera name substring, e.g. 'Simpang DPRD Arah Kota'")
    ap.add_argument("--camera-id", help="camera id from the API")
    ap.add_argument("--url", help="direct m3u8 url (bypasses the camera API)")
    ap.add_argument("--out", help="output .jsonl file")
    ap.add_argument("--model", help="yolo weights path (default: config FLOWSENSE_MODEL)")
    ap.add_argument("--interval", type=float, help="seconds between records (default: config)")
    ap.add_argument("--track", action="store_true",
                    help="use YOLO tracking to count unique lane crossings")
    ap.add_argument("--snapshot-only", action="store_true",
                    help="detect on one frame then exit (used for calibration)")
    ap.add_argument("--show", action="store_true", help="display annotated frames")
    ap.add_argument("--skip-detect", action="store_true",
                    help="just read frames (test stream before installing model)")
    ap.add_argument("--log-json", action="store_true", default=True,
                    help="structured JSON logs (default)")
    ap.add_argument("--log-level", default="INFO")
    return ap.parse_args(argv)


def build_record(ts, camera, summary, crossings=None):
    record = {
        "ts": int(ts),
        "camera_id": camera["id"],
        "camera": camera.get("nama", ""),
        "total_vehicles": summary.get("total_vehicles", 0),
        "per_lane": summary.get("per_lane", {}),
    }
    if crossings is not None:
        record["crossings"] = crossings
    return record


def per_lane_present(dets):
    counts = {}
    for d in dets:
        if d.get("lane"):
            counts[d["lane"]] = counts.get(d["lane"], 0) + 1
    return counts


def annotate(frame, lanes, summary):
    for name, poly in lanes.items():
        pts = np.array(poly, np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
        cx = int(np.mean([p[0] for p in poly]))
        cy = int(np.mean([p[1] for p in poly]))
        cv2.putText(frame, f"{name}: {summary['per_lane'].get(name, 0)}",
                    (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return frame


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = load_config()
    if args.interval is not None:
        cfg = replace(cfg, interval=args.interval)
    if args.model:
        cfg = replace(cfg, model_path=args.model)

    setup_logging(args.log_level, args.log_json)
    if not cfg.api_key:
        log.warning("FLOWSENSE_API_KEY is not set; copy .env.example to .env")

    if args.url:
        cam = {"id": "custom", "nama": "custom", "url": args.url}
    else:
        cameras = fetch_cameras(cfg)
        cam = find_camera(cameras, name=args.camera, cam_id=args.camera_id)
    camera_key = str(cam["id"])
    log.info("camera", extra={"camera_id": camera_key, "camera": cam.get("nama", "")})
    log.info("stream", extra={"url": cam["url"]})

    lanes = load_rois(cfg.rois_path, camera_key)
    if not lanes:
        log.warning("no lane ROIs for camera %s; run: python calibrate.py --camera-id %s",
                    camera_key, camera_key)

    model = None
    if not args.skip_detect:
        model = load_model(cfg.model_path)
        log.info("model loaded", extra={"model": cfg.model_path})

    stream = ReconnectingStream(cam["url"])
    stream.open()
    out_path = Path(args.out) if args.out else cfg.data_dir / f"connector_{camera_key}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    counter = TrackingCounter() if args.track else None
    last_emit = 0.0
    try:
        with open(out_path, "a", encoding="utf-8") as f:
            while True:
                ok, frame = stream.read()
                if not ok:
                    log.error("stream lost after reconnects; giving up")
                    break

                now = time.time()
                summary = {}
                crossings = None
                if model is not None:
                    if args.track:
                        results = model.track(frame, persist=True, verbose=False)
                        dets, pairs = track_summary(results, lanes, cfg.min_conf)
                        summary = {
                            "total_vehicles": len(dets),
                            "per_lane": per_lane_present(dets),
                            "vehicles": dets,
                        }
                        crossings = counter.update(pairs)
                    else:
                        results = model(frame, verbose=False)
                        summary = summarize_frame(results, lanes, cfg.min_conf)

                if now - last_emit >= cfg.interval:
                    record = build_record(now, cam, summary, crossings)
                    f.write(json.dumps(record, separators=(",", ":")) + "\n")
                    f.flush()
                    last_emit = now
                    log.info("record", extra={"camera_id": camera_key, "event": json.dumps(record)})

                if args.show and model is not None:
                    view = annotate(frame.copy(), lanes, summary)
                    cv2.imshow("flowsense", view)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                if args.snapshot_only:
                    break
    except KeyboardInterrupt:
        log.info("interrupted; shutting down")
    finally:
        stream.release()
        log.info("done", extra={"event": f"metadata -> {out_path}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 4: Create `flowsense/__main__.py`**

```python
"""Entry point for `python -m flowsense`."""
import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 5: Rewrite `connector.py` as a thin wrapper**

Replace the entire contents of `connector.py`:

```python
"""FlowSense edge connector entry point.

Thin wrapper around the flowsense.runner package. Run:
    python connector.py --camera "Simpang DPRD Arah Kota"
"""
import sys

from flowsense.runner import main

if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_runner.py -v`
Expected: 4 passed.

- [x] **Step 7: Verify the full suite still passes**

Run: `python -m pytest -q`
Expected: all tests pass (smoke, config, lanes, api, telemetry, detector, counter, stream, runner).

- [x] **Step 8: Verify CLI wiring offline**

Run: `python connector.py --help`
Expected: usage text listing `--camera`, `--camera-id`, `--url`, `--out`, `--model`, `--interval`, `--track`, `--snapshot-only`, `--show`, `--skip-detect`, `--log-json`, `--log-level`.

- [x] **Step 9: Optional live sanity check (needs API key + model installed)**

Run: `python connector.py --camera-id 30 --snapshot-only`
Expected: logs `camera`, `model loaded`, one `record`, then `done`. Requires `pip install -r requirements.txt` and a valid `FLOWSENSE_API_KEY`. If the environment lacks either, skip this step.

- [x] **Step 10: Commit**

```bash
git add flowsense/runner.py flowsense/__main__.py connector.py tests/test_runner.py
git commit -m "refactor: wire all modules into runner; connector.py becomes a thin entry point"
```

---

### Task 10: calibrate.py reads API key from env

**Files:**
- Modify: `calibrate.py` (lines 24-25 only: remove hardcoded key)

**Interfaces:**
- Consumes: `load_config` from `flowsense.config`.
- Produces: none (no code depends on this change).

- [x] **Step 1: Replace the hardcoded API key**

In `calibrate.py`, replace lines 24-25:

```python
API_URL = "https://kudussehat.kuduskab.go.id/api/get-cctv"
API_KEY = "&lt;REDACTED&gt;"
```

with:

```python
from flowsense.config import load_config

_CONFIG = load_config()
API_URL = _CONFIG.api_url
API_KEY = _CONFIG.api_key
```

- [x] **Step 2: Fail fast when the key is missing**

In `calibrate.py`, at the top of `main()`, after `args = ap.parse_args()`, insert:

```python
    if not API_KEY:
        raise SystemExit(
            "FLOWSENSE_API_KEY is not set; copy .env.example to .env and fill it in"
        )
```

- [x] **Step 3: Verify it imports and validates**

Run: `python calibrate.py --help`
Expected: usage text prints (imports fine). Also confirm no API key string remains in source:

Run: `python -c "import calibrate; print('ok')"`
Expected: `ok` if `.env` exists with a key, or a `SystemExit` message about the missing key if it doesn't — either proves the old hardcoded key is gone.

- [x] **Step 4: Grep to confirm the secret is removed**

Run: `rg -n "sdsi7239[0-9]" C:\Users\legion\flowsense`
Expected: no matches (secret no longer in any file).

- [x] **Step 5: Commit**

```bash
git add calibrate.py
git commit -m "fix: read Kudus API key from env/.env in calibrate.py"
```

---

### Task 11: README + final verification

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: all modules; documents the final CLI, env vars, schema, and test commands.

- [x] **Step 1: Write `README.md`**

```markdown
# FlowSense

Edge vehicle detection for Kudus CCTV streams. Reads an HLS feed, runs
YOLOv11, maps detections into per-lane ROIs, and emits tiny metadata JSON
(kilobytes, not video). Optionally uses YOLO tracking to count each vehicle
once per lane crossing.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env     # then fill in FLOWSENSE_API_KEY
```

## Calibrate lane ROIs

Draw per-lane polygons on a frame; saved to `config/rois.json`.

```bash
python calibrate.py --camera-id 30 --lanes "kota,ploso,demak,sekoe"
```

## Run the connector

```bash
python connector.py --camera "Simpang DPRD Arah Kota"          # by name
python connector.py --camera-id 30                             # by id
python connector.py --url <m3u8> --out data/custom.jsonl       # direct URL
python connector.py --camera-id 30 --track                     # unique lane crossings
python connector.py --camera-id 30 --snapshot-only             # one frame, then exit
python connector.py --camera-id 30 --skip-detect               # stream check, no model
python -m flowsense --camera-id 30                             # module entry point
```

### Output

One JSON object per line in `data/connector_<camera_id>.jsonl`:

```json
{"ts":1755000000,"camera_id":30,"camera":"...","total_vehicles":4,"per_lane":{"kota":2}}
```

With `--track`, records also include cumulative `crossings`:

```json
{"ts":1755000000,"camera_id":30,"camera":"...","total_vehicles":2,"per_lane":{"kota":1},"crossings":{"kota":12}}
```

## Configuration (env / .env)

| Variable | Default | Meaning |
|---|---|---|
| `FLOWSENSE_API_KEY` | *(none)* | Kudus CCTV API key (required) |
| `FLOWSENSE_API_URL` | `https://kudussehat.kuduskab.go.id/api/get-cctv` | Camera list endpoint |
| `FLOWSENSE_API_TIMEOUT` | `25` | API request timeout (s) |
| `FLOWSENSE_API_RETRIES` | `3` | API retries before giving up |
| `FLOWSENSE_API_BACKOFF` | `2` | Base backoff (s), doubled per retry |
| `FLOWSENSE_MIN_CONF` | `0.35` | Min YOLO confidence for vehicles |
| `FLOWSENSE_INTERVAL` | `2` | Seconds between metadata records |
| `FLOWSENSE_MODEL` | `yolo11n.pt` | YOLO weights path |

## Tests

```bash
python -m pytest -q
```

No network or camera access is needed; stream and API code are tested with fakes.
```

- [x] **Step 2: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass. Final count: 1 (smoke) + 4 (config) + 6 (lanes) + 6 (api) + 3 (telemetry) + 4 (detector) + 4 (counter) + 3 (stream) + 4 (runner) = **35 passed**.

- [x] **Step 3: Verify both entry points work offline**

Run: `python connector.py --help` and `python -m flowsense --help`
Expected: both print usage.

- [x] **Step 4: Verify no secret remains in tracked files**

Run: `rg -n "sdsi7239[0-9]" . --hidden -g "!.git"`
Expected: no matches.

- [x] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, usage, schema, config, and tests"
```

---

### Task 12: Density classification (klasifikasi kepadatan)

**Files:**
- Create: `flowsense/density.py`
- Create: `tests/test_density.py`

**Interfaces:**
- Consumes: nothing (pure logic, stdlib only).
- Produces:
  - `DENSITY_LEVELS: tuple[str, ...]` — `("lancar", "sedang", "padat")` (smooth / moderate / heavy), matching the Indonesian traffic domain in the diagram.
  - `density_from_count(count: int, thresholds: tuple[int, int] = (3, 8)) -> str` — `count <= thresholds[0]` → `"lancar"`, `<= thresholds[1]` → `"sedang"`, else `"padat"`.
  - `classify_density(per_lane: dict[str, int], thresholds: tuple[int, int] = (3, 8)) -> dict[str, str]` — returns `{lane: label}` for every lane present in `per_lane` (lanes with 0 vehicles → `"lancar"`). Pure and offline-testable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_density.py`:

```python
from flowsense.density import classify_density, density_from_count

def test_density_from_count_thresholds():
    assert density_from_count(0) == "lancar"
    assert density_from_count(3) == "lancar"
    assert density_from_count(4) == "sedang"
    assert density_from_count(8) == "sedang"
    assert density_from_count(9) == "padat"

def test_classify_density_per_lane():
    per_lane = {"kota": 2, "ploso": 5, "demak": 12}
    assert classify_density(per_lane) == {
        "kota": "lancar",
        "ploso": "sedang",
        "demak": "padat",
    }

def test_classify_density_zero_is_lancar():
    assert classify_density({"kota": 0, "ploso": 0}) == {"kota": "lancar", "ploso": "lancar"}

def test_classify_density_custom_thresholds():
    assert classify_density({"kota": 10}, thresholds=(5, 15)) == {"kota": "sedang"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_density.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowsense.density'`.

- [ ] **Step 3: Implement the minimal module**

Create `flowsense/density.py`:

```python
"""Per-lane traffic density classification (klasifikasi kepadatan)."""

DENSITY_LEVELS = ("lancar", "sedang", "padat")


def density_from_count(count: int, thresholds: tuple[int, int] = (3, 8)) -> str:
    """Map a vehicle count to a density label."""
    low, high = thresholds
    if count <= low:
        return "lancar"
    if count <= high:
        return "sedang"
    return "padat"


def classify_density(per_lane: dict, thresholds: tuple[int, int] = (3, 8)) -> dict:
    """Classify every lane's vehicle count into a density label."""
    return {lane: density_from_count(count, thresholds) for lane, count in per_lane.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_density.py -v`
Expected: 4 passed.

- [ ] **Step 5: Wire density into the runner record (additive schema field)**

In `flowsense/runner.py`:
  - import `classify_density` from `.density`;
  - after building `summary`, compute `density = classify_density(summary.get("per_lane", {}))`;
  - extend `build_record(ts, camera, summary, crossings=None, density=None)` to include `"density": density` only when `density is not None`;
  - emit it in the main loop alongside `crossings`.

This is **additive** — existing record keys (`ts`, `camera_id`, `camera`, `total_vehicles`, `per_lane`) are unchanged, and `density` is omitted unless classification runs, satisfying the schema constraint in Global Constraints.

- [ ] **Step 6: Extend `tests/test_runner.py`**

Add a `test_build_record_with_density` asserting `r["density"] == {"kota": "sedang"}` when `density={"kota": "sedang"}` is passed.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass (smoke, config, lanes, api, telemetry, detector, counter, stream, runner, density).

- [ ] **Step 8: Commit**

```bash
git add flowsense/density.py flowsense/runner.py tests/test_density.py tests/test_runner.py
git commit -m "feat: add per-lane density classification (klasifikasi kepadatan)"
```

---

## Self-Review

- **Spec coverage (all six requested areas):**
  - Reliability & error handling → Task 4 (API retry/backoff), Task 8 (ReconnectingStream), Task 9 (graceful shutdown, bounded reconnects).
  - Security (secrets to env) → Tasks 1, 2 (env/.env, gitignored, key removed), Task 10 (calibrate.py).
  - Test coverage → Tasks 1-9 each ship offline unit tests; Task 11 runs the full suite.
  - Structure & maintainability → Tasks 1, 3, 6, 9 (package split, thin `connector.py`), Task 11 (README).
  - Observability → Task 5 (JSON logging), Task 9 (startup/reconnect/record/done logs).
  - Core quality (tracking + counting + density) → Tasks 6, 7 (`track_summary` + `TrackingCounter`), density classification Task 12 (`classify_density`), wired in Task 9/12 via the additive `density` record field.
- **Placeholder scan:** every task contains concrete code, exact test commands, and expected results. No "TBD"/"add handling" placeholders.
- **Type consistency:** `lane_from_detection(bbox, lanes)` (Task 3) is called by `summarize_frame`/`track_summary` (Task 6) with `bbox`; `track_summary` returns `(dets, [(track_id, lane)])` consumed by `TrackingCounter.update` (Task 7) in Task 9; `build_record(ts, camera, summary, crossings=None, density=None)` is defined in Task 9 and extended in Task 12; `Config` field names match `load_config`/`.env.example` throughout. `per_lane` key and `vehicles` list remain in `summary` across both detection modes so `annotate` keeps working; `density` (Task 12) is an additive optional record field keyed off `per_lane`.

## Roadmap — downstream components (diagram layers 3 → 6)

The reference diagram extends well beyond the edge connector this plan covers. These are **out of scope for the connector refactor** but are the connector's consumers; the record schema and snapshot output are the contracts they build on.

- [x] **Layer 3 — DATABASE (PostgreSQL + TimescaleDB):** ingest the `.jsonl` records (or stream them directly). Add a `flowsense/sink.py` `RecordSink` interface with a local `.jsonl` implementation (already effectively done by the runner) and a `PostgresSink` using `psycopg`/TimescaleDB. Hypertable on `ts` for the per-minute aggregation ("Agregasi 1 menit") the diagram shows feeding layer 4.
- [x] **Layer 3b — STORAGE SERVICE (Garage/disk):** persist Snapshot JPEGs (currently only produced in `--snapshot-only` calibration) on a regular cadence to object storage; add a `SnapshotSink` alongside `RecordSink`.
- **Layer 4 — API/BACKEND (FastAPI + JWT):** serve records/snapshots to operators; JWT auth for the operator flavor. Exposes the per-lane counts that layer 5/6 consume.
- **Layer 5 — CLIENT (Flutter / Riverpod / flutter_map):** two flavors — `warga` (public) and `operator` (authenticated). Reads from layer 4.
- **Layer 5/6 — SIMULATION (SUMO + TraCI):** inputs the lane counts from layer 3, outputs wait-time delta ("selisih waktu tunggu"). Reference implementation already in `Reference/sumo-adaptive-traffic-signal-control-main`; wire its input to the connector's per-lane counts.

> NOTE: adding PostgreSQL / object-storage / FastAPI / SUMO dependencies would relax the "no new dependencies" constraint in Global Constraints and is therefore tracked here as future work, not part of the connector plan.
