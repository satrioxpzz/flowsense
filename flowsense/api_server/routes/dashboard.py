"""Live ops dashboard route (promoted from sketches/001-utilitarian-dense).

Serves:
  GET /api/v1/dashboard/data  -> JSON snapshot of all connector jsonl files
  GET /dashboard              -> the Utilitarian-Dense HTML dashboard (live)

Data is read directly from ``data/connector_*.jsonl`` (the edge connector
output) so the dashboard works even with an empty database.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

# Capacity used to derive status + density from a single lane's vehicle count.
LANE_WARN = 15
LANE_CRIT = 30
SPARK_POINTS = 12

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = ROOT / "data"

router = APIRouter()


def _read_jsonl(path: Path, max_lines: int = 5000) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return out


def _build_camera(path: Path) -> dict[str, Any]:
    recs = _read_jsonl(path)
    cam_id = path.stem.replace("connector_", "")
    name = f"Camera {cam_id}"
    lanes: dict[str, int] = {}
    spark: list[int] = []
    if recs:
        # Pick the most recent record that actually detected vehicles. Prefer
        # one whose per-lane/crossing split is non-zero; otherwise accept a
        # record with total_vehicles > 0 (the live feed sometimes emits an
        # all-zero per_lane alongside a positive total). Fall back to the last
        # record if the stream has gone quiet.
        last = recs[-1]
        nonempty = next(
            (r for r in reversed(recs)
             if any((r.get("per_lane") or {}).values())
             or any((r.get("crossings") or {}).values())
             or (r.get("total_vehicles") or 0) > 0),
            last,
        )
        name = nonempty.get("camera") or name
        if nonempty.get("per_lane"):
            lanes = {k: int(v) for k, v in nonempty["per_lane"].items()}
        elif nonempty.get("crossings"):
            lanes = {k: int(v) for k, v in nonempty["crossings"].items()}
        spark = [int(r.get("total_vehicles", 0)) for r in recs[-SPARK_POINTS:]]

    total = sum(lanes.values()) or int(nonempty.get("total_vehicles", 0)) if recs else 0
    max_lane = max(lanes.values()) if lanes else 0
    if max_lane >= LANE_CRIT:
        status = "crit"
    elif max_lane >= LANE_WARN:
        status = "warn"
    else:
        status = "ok"
    return {
        "id": cam_id,
        "name": name,
        "status": status,
        "lanes": lanes,
        "total": total,
        "spark": spark,
    }


def _snapshot() -> dict[str, Any]:
    cams: list[dict[str, Any]] = []
    if DATA_DIR.exists():
        for p in sorted(DATA_DIR.glob("connector_*.jsonl")):
            cams.append(_build_camera(p))

    total_veh = sum(c["total"] for c in cams)
    alerts = [c for c in cams if c["status"] in ("warn", "crit")]
    n_crit = sum(1 for c in cams if c["status"] == "crit")
    densities = []
    for c in cams:
        if c["lanes"]:
            densities.append(max(c["lanes"].values()) / LANE_CRIT)
    avg_density = int(sum(densities) / len(densities) * 100) if densities else 0

    return {
        "cameras": cams,
        "kpis": {
            "vehicles_per_min": total_veh,
            "active_cameras": len(cams),
            "alerts": len(alerts),
            "critical": n_crit,
            "avg_density_pct": avg_density,
        },
        "alerts": [
            {
                "camera": c["name"],
                "severity": c["status"],
                "detail": f"Lane max {max(c['lanes'].values())} kendaraan (cam {c['id']})",
            }
            for c in alerts
        ],
    }


@router.get("/data")
async def dashboard_data() -> JSONResponse:
    return JSONResponse(_snapshot())


@router.get("", include_in_schema=False)
async def dashboard_page(request: Request) -> HTMLResponse:
    html_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    # Fallback inline minimal page if template missing.
    return HTMLResponse(
        "<h1>FlowSense Dashboard</h1><p>template not found</p>"
        "<script>location.href='/api/v1/dashboard/data'</script>"
    )
