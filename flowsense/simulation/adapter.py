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

    Uses 'crossings' deltas between time bins to compute vehicles/hour.
    Falls back to 'per_lane' snapshot counts when crossings are unavailable.

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

    mapping = lane_map or DEFAULT_LANE_MAP
    first_ts = records[0]["ts"]
    last_ts = records[-1]["ts"]

    # Group records into time bins
    bins: dict[int, list[dict]] = defaultdict(list)
    for rec in records:
        bin_idx = (rec["ts"] - first_ts) // bin_seconds
        bins[bin_idx].append(rec)

    # Build per-direction flow volumes
    result: dict[str, list[tuple[int, int, int]]] = {
        "north": [], "south": [], "east": [], "west": []
    }

    has_crossings = any("crossings" in r for r in records)

    sorted_bin_keys = sorted(bins.keys())
    for bin_idx in sorted_bin_keys:
        bin_records = bins[bin_idx]
        begin = int(first_ts + bin_idx * bin_seconds - first_ts)  # relative seconds
        end = begin + bin_seconds

        direction_counts: dict[str, int] = defaultdict(int)

        if has_crossings:
            # Use crossing deltas: last_crossings - first_crossings in this bin
            first_rec = bin_records[0]
            last_rec = bin_records[-1]
            first_cross = first_rec.get("crossings", {})
            last_cross = last_rec.get("crossings", {})

            for lane_name, direction in mapping.items():
                delta = last_cross.get(lane_name, 0) - first_cross.get(lane_name, 0)
                direction_counts[direction] += max(0, delta)
        else:
            # FALLBACK (coarse estimate, NOT a true flow measurement):
            # the per_lane snapshot is a count of vehicles *present* (occupancy),
            # not a rate. We average it across the bin and label it explicitly as
            # an estimate. We do NOT fabricate a minimum of 10 vph for directions
            # that are genuinely empty (P1-13).
            for rec in bin_records:
                per_lane = rec.get("per_lane", {})
                for lane_name, direction in mapping.items():
                    direction_counts[direction] += per_lane.get(lane_name, 0)
            n = len(bin_records)
            if n > 0:
                for d in direction_counts:
                    direction_counts[d] = direction_counts[d] // n

        # Convert to vehicles/hour. Allow 0 for genuinely empty directions
        # (P1-13): do not invent a minimum flow.
        scale = 3600 / bin_seconds
        for direction in result:
            vph = int(direction_counts.get(direction, 0) * scale)
            result[direction].append((begin, end, vph))

    return result
