"""Adapter to convert FlowSense CCTV vehicle counts into SUMO traffic demand."""
import json
import logging
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Optional

log = logging.getLogger("flowsense.simulation")

# Single-letter compass codes used in simulation_config.toml [flowsense] block
# (e.g. lane_mapping_kota = "S") expanded to full direction names.
_COMPASS = {"N": "north", "S": "south", "E": "east", "W": "west"}
_TOML_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "simulation_config.toml"

# Hardcoded fallback — used only if the TOML is missing or has no [flowsense] block.
_FALLBACK_LANE_MAP = {
    "kota": "south",
    "ploso": "north",
    "demak": "west",
    "sekoe": "east",
}

# P2-9: the [flowsense] TOML block used to be dead config (never read). Now we
# build the default lane map FROM it so editing the TOML actually changes mapping.
def _load_lane_map() -> dict:
    if _TOML_PATH.exists():
        try:
            with open(_TOML_PATH, "rb") as f:
                cfg = tomllib.load(f)
            fs = cfg.get("flowsense", {})
            mapping = {}
            for key, val in fs.items():
                if key.startswith("lane_mapping_"):
                    lane = key[len("lane_mapping_"):]
                    code = str(val).strip().upper()
                    direction = _COMPASS.get(code, code.lower())
                    mapping[lane] = direction
            if mapping:
                return mapping
        except Exception:
            log.warning("Failed to read lane mapping from %s; using fallback", _TOML_PATH)
    return dict(_FALLBACK_LANE_MAP)

DEFAULT_LANE_MAP = _load_lane_map()


def lane_to_direction(lane_name: str, lane_map: dict | None = None) -> str:
    """Map a FlowSense lane name to a SUMO compass direction.

    Args:
        lane_name: FlowSense lane name (e.g. 'kota', 'ploso').
        lane_map: Optional override mapping. Defaults to DEFAULT_LANE_MAP.

    Returns:
        SUMO direction string ('north', 'south', 'east', 'west').

    Raises:
        KeyError: If lane_name is not found in the mapping.
    """
    mapping = lane_map or DEFAULT_LANE_MAP
    key = lane_name.lower().strip()
    if key not in mapping:
        raise KeyError(f"Unknown lane name '{lane_name}'. Known: {list(mapping.keys())}")
    return mapping[key]


def load_records(
    jsonl_path: Path,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
) -> list[dict]:
    """Load FlowSense .jsonl records, optionally filtering by timestamp range.

    Args:
        jsonl_path: Path to the .jsonl file.
        start_ts: Inclusive lower bound on the 'ts' field (unix epoch seconds).
        end_ts: Inclusive upper bound on the 'ts' field.

    Returns:
        List of parsed record dicts, sorted by 'ts'.
    """
    path = Path(jsonl_path)
    if not path.exists():
        log.warning("Data file not found: %s", path)
        return []

    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = rec.get("ts")
        if ts is None:
            continue
        if start_ts is not None and ts < start_ts:
            continue
        if end_ts is not None and ts > end_ts:
            continue
        records.append(rec)

    records.sort(key=lambda r: r["ts"])
    return records


def aggregate_flows(
    records: list[dict],
    bin_seconds: int = 900,
    lane_map: dict | None = None,
) -> dict[str, list[tuple[int, int, int]]]:
    """Convert FlowSense records into SUMO-compatible flow volumes per direction.

    Demand is derived from the **per-lane cumulative ``crossings`` counter**,
    counting actual crossings as the sum of positive per-frame deltas. The
    counter resets intermittently (process restart / wrap), which appears as a
    negative step; we treat a reset as the counter wrapping to 0, so the
    increment equals the post-reset value rather than being lost. This avoids
    the previous bug where ``last - first`` over a bin with resets collapsed to
    ~0 vph even under real traffic (Codex P1 review).

    When the ``crossings`` field is absent entirely, falls back to the
    authoritative per-frame ``total_vehicles`` (a real count, never an
    occupancy snapshot) split across directions by observed ``per_lane``
    occupancy *share* — occupancy is used only as a directional-split proxy,
    never scaled directly to vph (P1-13: do not treat occupancy as a flow rate,
    and do not fabricate traffic on silent directions).

    Args:
        records: FlowSense .jsonl records (sorted by ts).
        bin_seconds: Time bin size in seconds (default 900 = 15 min).
        lane_map: Optional lane-to-direction mapping override.

    Returns:
        Dict mapping SUMO direction ('north', 'south', 'east', 'west') to a
        list of (begin_sec, end_sec, vehicles_per_hour) tuples matching the
        SUMO TRAFFIC_VOLUME format.
    """
    if not records:
        return {}
    if bin_seconds <= 0:
        raise ValueError(f"bin_seconds must be a positive integer, got {bin_seconds}")

    mapping = lane_map or DEFAULT_LANE_MAP
    first_ts = records[0]["ts"]

    # Group records into time bins (relative to first_ts).
    bins: dict[int, list[dict]] = defaultdict(list)
    for rec in records:
        bin_idx = (rec["ts"] - first_ts) // bin_seconds
        bins[bin_idx].append(rec)

    result: dict[str, list[tuple[int, int, int]]] = {
        "north": [], "south": [], "east": [], "west": []
    }

    has_crossings = any("crossings" in r for r in records)
    scale = 3600 / bin_seconds

    for bin_idx in sorted(bins):
        bin_records = bins[bin_idx]
        begin = int(bin_idx * bin_seconds)  # seconds relative to first_ts
        end = begin + bin_seconds
        direction_counts: dict[str, int] = defaultdict(int)

        if has_crossings:
            # Count actual crossings per lane: sum of positive per-frame
            # deltas, with reset handling (negative step = counter wrapped).
            for lane_name, direction in mapping.items():
                prev: int | None = None
                for rec in bin_records:
                    cur = (rec.get("crossings") or {}).get(lane_name, 0)
                    if prev is not None:
                        delta = cur - prev
                        if delta > 0:
                            direction_counts[direction] += delta
                        elif delta < 0:
                            # Reset: counter wrapped to 0; the new baseline is
                            # itself the vehicles counted since the reset.
                            direction_counts[direction] += cur
                    prev = cur
        else:
            # No crossings field at all: use the per-frame total_vehicles
            # (a genuine count) and split it by per_lane occupancy share.
            bin_total = sum((rec.get("total_vehicles") or 0) for rec in bin_records)
            last_per_lane = bin_records[-1].get("per_lane") or {}
            occ = {lane_name: last_per_lane.get(lane_name, 0) for lane_name in mapping}
            tot_occ = sum(occ.values())
            if tot_occ > 0:
                for lane_name, direction in mapping.items():
                    direction_counts[direction] += int(
                        bin_total * occ[lane_name] / tot_occ
                    )
            elif bin_total:
                # No directional signal: place the total on the first mapped
                # lane rather than inventing four-way traffic.
                first_dir = mapping[next(iter(mapping))]
                direction_counts[first_dir] += bin_total

        # Convert to vehicles/hour. Genuinely empty directions stay 0 vph.
        for direction in result:
            vph = int(direction_counts.get(direction, 0) * scale)
            result[direction].append((begin, end, vph))

    return result
