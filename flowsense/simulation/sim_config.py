import os
import random
from pathlib import Path

# ---------------------------------------------------------
#  TOML CONFIGURATION LOADER
# ---------------------------------------------------------
# Load external config if available, otherwise use defaults
_CONFIG = {}
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "simulation_config.toml"

try:
    import tomllib
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "rb") as f:
            _CONFIG = tomllib.load(f)
except ImportError:
    # Python < 3.11 fallback — use defaults
    pass
except Exception as e:
    # P2-10: previously swallowed silently — a malformed TOML would silently fall
    # back to defaults, hiding misconfiguration. Log it instead.
    import logging
    logging.getLogger(__name__).warning("Failed to parse %s, using defaults: %s", _CONFIG_PATH, e)

def _get(section: str, key: str, default):
    """Retrieve a value from the loaded TOML config with a fallback default."""
    return _CONFIG.get(section, {}).get(key, default)

# ---------------------------------------------------------
#  DIRECTORY PATHS & UTILITIES
# ---------------------------------------------------------
BUILD_DIR = "simulation/map/build"    # Output folder for automated generation files
INPUT_DIR = "simulation/map"          # Input folder for static XML infrastructure source files

# ---------------------------------------------------------
#  SIMULATION PARAMETERS
# ---------------------------------------------------------
SIM_DURATION = int(_get("simulation", "duration", 3600))
RANDOM_SEED  = int(_get("simulation", "random_seed", 42))
STEP_LENGTH  = float(_get("simulation", "step_length", 0.1))
# P2-12: do NOT call random.seed() at import time — it hijacks the global RNG of
# the whole process. Use a dedicated, isolated Random instance instead.
_rng = random.Random(RANDOM_SEED)

# ---------------------------------------------------------
#  ALGORITHM PARAMETERS (externalized from hardcoded values)
# ---------------------------------------------------------
MIN_GREEN            = float(_get("algorithm", "min_green", 10.0))
MAX_GREEN            = float(_get("algorithm", "max_green", 50.0))
YELLOW_DURATION      = float(_get("algorithm", "yellow_duration", 4.0))
STARVATION_THRESHOLD = float(_get("algorithm", "starvation_threshold", 120.0))
MAX_QUEUE_CAPACITY   = int(_get("algorithm", "max_queue_capacity", 30))

# ---------------------------------------------------------
#  EMERGENCY VEHICLE PREEMPTION (EVP) PARAMETERS
# ---------------------------------------------------------
EVP_ENABLED          = bool(_get("evp", "enabled", True))
EVP_DETECTION_RADIUS = float(_get("evp", "detection_radius", 200.0))
EVP_COOLDOWN         = float(_get("evp", "cooldown_seconds", 10.0))
EVP_SPAWN_PROB       = float(_get("evp", "spawn_probability", 0.01))

# ---------------------------------------------------------
#  LOGGING PARAMETERS
# ---------------------------------------------------------
LOG_ENABLED        = bool(_get("logging", "enabled", True))
LOG_INTERVAL_STEPS = int(_get("logging", "interval_steps", 100))
LOG_OUTPUT_FILE    = str(_get("logging", "output_file", "output/simulation_log.csv"))

# Turn maneuvers proportions per direction: (straight, left, right)
TURN_RATIO = {
    "north": (0.55, 0.25, 0.20),
    "south": (0.55, 0.20, 0.25),
    "west":  (0.50, 0.25, 0.25),
    "east":  (0.50, 0.25, 0.25),
}

# Routes based on origin direction and maneuver type
# Left turns bypass the main intersection via dedicated slip roads (bypass lanes)
ROUTES = {
    "north": {
        "straight": ("north_in_1 north_in_2", "south_out_1 south_out_2"),
        "right":    ("north_in_1 north_in_2", "west_out_1 west_out_2"),
        "left":     ("north_in_1", "slip_ne east_out_2"),
    },
    "south": {
        "straight": ("south_in_1 south_in_2", "north_out_1 north_out_2"),
        "right":    ("south_in_1 south_in_2", "east_out_1 east_out_2"),
        "left":     ("south_in_1", "slip_sw west_out_2"),
    },
    "west": {
        "straight": ("west_in_1 west_in_2", "east_out_1 east_out_2"),
        "right":    ("west_in_1 west_in_2", "south_out_1 south_out_2"),
        "left":     ("west_in_1", "slip_wn north_out_2"),
    },
    "east": {
        "straight": ("east_in_1 east_in_2", "west_out_1 west_out_2"),
        "right":    ("east_in_1 east_in_2", "north_out_1 north_out_2"),
        "left":     ("east_in_1", "slip_es south_out_2"),
    },
}

# Vehicle types definition: (id, accel, decel, length_m, maxSpeed_ms, sigma, color_rgb, proportion)
VEHICLE_TYPES = [
    ("car",        2.6, 4.5,  4.5,  13.89, 0.5, "255,200,0",  0.63),
    ("motorcycle", 3.0, 5.0,  2.0,  16.67, 0.6, "0,180,255",  0.20),
    ("bus",        1.5, 3.5, 12.0,  11.11, 0.3, "50,200,50",  0.07),
    ("truck",      1.2, 3.0, 10.0,  11.11, 0.3, "200,100,50", 0.06),
]

# Emergency vehicle types (spawned separately with low probability)
EMERGENCY_VEHICLE_TYPES = [
    ("ambulance",  2.8, 5.0,  6.0,  19.44, 0.2, "255,0,0",    0.60),
    ("fire_truck", 2.0, 4.0, 10.0,  16.67, 0.2, "255,50,0",   0.40),
]

GUI_SHAPE = {
    "car": "passenger", "motorcycle": "motorcycle",
    "bus": "bus",       "truck": "truck",
    "ambulance": "emergency", "fire_truck": "firebrigade",
}

# Base traffic volume (will be updated dynamically via CLI)
TRAFFIC_VOLUME = {
    "north": [], "south": [], "west": [], "east": []
}

# Default volume profiles (can be overridden from TOML)
_DEFAULT_NORMAL_VOL = _get("traffic", "normal_volumes",
    [(0, 900, 180), (900, 1800, 350), (1800, 2700, 220), (2700, 3600, 320)]
)
_DEFAULT_CONGESTED_VOL = _get("traffic", "congested_volumes",
    [(0, 900, 800), (900, 1800, 1500), (1800, 2700, 900), (2700, 3600, 1400)]
)

def set_traffic_volumes(congested_directions):
    """Sets dynamic traffic volume flow rates based on CLI input configurations."""
    # Convert from TOML nested lists to tuples if needed
    normal_vol = [tuple(v) for v in _DEFAULT_NORMAL_VOL]
    congested_vol = [tuple(v) for v in _DEFAULT_CONGESTED_VOL]

    for direction in ["north", "south", "west", "east"]:
        if direction in congested_directions:
            TRAFFIC_VOLUME[direction] = congested_vol
        else:
            TRAFFIC_VOLUME[direction] = normal_vol


def set_real_traffic_volumes(flows: dict):
    """Use real FlowSense detection counts (from adapter.aggregate_flows) as the
    SUMO demand instead of synthetic profiles.

    Args:
        flows: {direction: [(begin, end, vph), ...]} — same shape as TRAFFIC_VOLUME.
    """
    for direction in ["north", "south", "west", "east"]:
        TRAFFIC_VOLUME[direction] = list(flows.get(direction, []))
