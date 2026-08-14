"""
SUMO XML INFRASTRUCTURE GENERATOR
Builds road network, vehicle routes, sensor definitions, and simulation config.
===================================================================
IMPROVEMENTS:
  - Emergency vehicle route generation (ambulance, fire_truck)
  - Cross-platform executable resolution (no hardcoded .exe suffix)
"""

import os
import sys
import shutil
import random
import subprocess
import xml.etree.ElementTree as ET
from xml.dom import minidom
import logging

from .sim_config import (
    BUILD_DIR, INPUT_DIR, SIM_DURATION, RANDOM_SEED, STEP_LENGTH,
    ROUTES, TRAFFIC_VOLUME, VEHICLE_TYPES, EMERGENCY_VEHICLE_TYPES,
    GUI_SHAPE, TURN_RATIO, EVP_ENABLED, EVP_SPAWN_PROB,
)

log = logging.getLogger("flowsense.simulation")

def ok(msg: str):
    log.info(f"  [OK] {msg}")

def _exe_name(base: str) -> str:
    """Return the platform-appropriate executable name."""
    if sys.platform == "win32":
        return base + ".exe"
    return base

def find_exe(name: str) -> str:
    """Finds a SUMO executable in system PATH or SUMO_HOME bin.
    Accepts both 'netconvert' and 'netconvert.exe' — auto-resolves per platform.
    """
    # Strip .exe suffix if provided, then re-add platform-appropriate suffix
    base_name = name.replace(".exe", "")
    platform_name = _exe_name(base_name)
    
    found = shutil.which(platform_name)
    if found:
        return found
    
    # Also try without extension (Linux/macOS)
    found = shutil.which(base_name)
    if found:
        return found
    
    sumo_home = os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo")
    sumo_bin = os.path.join(sumo_home, "bin")
    
    for candidate_name in [platform_name, base_name]:
        candidate = os.path.join(sumo_bin, candidate_name)
        if os.path.isfile(candidate):
            return candidate
    
    raise FileNotFoundError(
        f"Unable to locate executable '{base_name}'.\n"
        f"Ensure SUMO is installed correctly and SUMO_HOME is set in your environment variables.\n"
        f"Current SUMO_HOME path: {sumo_home}"
    )

def prettify(elem) -> str:
    raw = ET.tostring(elem, encoding="unicode")
    reparsed = minidom.parseString(raw)
    return reparsed.toprettyxml(indent="    ", encoding=None)

def write_xml(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        lines = content.split("\n")
        if lines[0].startswith("<?xml"):
            lines = lines[1:]
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("\n".join(lines))
    ok(os.path.basename(path))

def build_network(tls_layout="opposites"):
    log.info("\n[1/3] Building road network layout with netconvert...")
    netconvert_bin = find_exe("netconvert")
    cmd = [
        netconvert_bin,
        "--node-files",            os.path.join(INPUT_DIR, "nodes.nod.xml"),
        "--edge-files",            os.path.join(INPUT_DIR, "edges.edg.xml"),
        "--connection-files",      os.path.join(INPUT_DIR, "connections.con.xml"),
        "--output-file",           os.path.join(BUILD_DIR, "net.net.xml"),
        "--tls.default-type",      "static",
        "--tls.layout",            tls_layout,
        "--tls.green.time",        "35",
        "--tls.yellow.time",       "4",
        "--tls.red.time",          "2",
        "--no-turnarounds",        "true",
        "--junctions.corner-detail", "5",
        "--lefthand",              "true",
        "--geometry.remove",       "true",
        "--verbose",               "false",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        log.error(f"netconvert error:\n{result.stderr}")
        raise RuntimeError(f"netconvert failed: {result.stderr}")
    ok("net.net.xml successfully generated")

def build_routes(orderliness="orderly"):
    log.info("[2/3] Generating dynamic vehicle routes...")

    root = ET.Element("routes")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("xsi:noNamespaceSchemaLocation",
             "http://sumo.dlr.de/xsd/routes_file.xsd")

    # -- Define vType elements (regular vehicles) --
    for vtype_id, accel, decel, length, maxspeed, sigma, color, _ in VEHICLE_TYPES:
        actual_sigma = sigma if orderliness == "chaotic" else 0.1
        actual_tau   = 1.0 if orderliness == "orderly" else 0.5

        vtype = ET.SubElement(root, "vType")
        vtype.set("id",          vtype_id)
        vtype.set("accel",       str(accel))
        vtype.set("decel",       str(decel))
        vtype.set("length",      str(length))
        vtype.set("maxSpeed",    str(maxspeed))
        vtype.set("sigma",       str(actual_sigma))
        vtype.set("tau",         str(actual_tau))
        vtype.set("color",       color)
        vtype.set("guiShape",    GUI_SHAPE[vtype_id])
        vtype.set("speedFactor", "normc(1.0,0.1,0.8,1.2)")

    # -- Define emergency vType elements --
    if EVP_ENABLED:
        for vtype_id, accel, decel, length, maxspeed, sigma, color, _ in EMERGENCY_VEHICLE_TYPES:
            vtype = ET.SubElement(root, "vType")
            vtype.set("id",          vtype_id)
            vtype.set("accel",       str(accel))
            vtype.set("decel",       str(decel))
            vtype.set("length",      str(length))
            vtype.set("maxSpeed",    str(maxspeed))
            vtype.set("sigma",       str(sigma))
            vtype.set("tau",         "0.8")   # Moderate following distance
            vtype.set("color",       color)
            vtype.set("guiShape",    GUI_SHAPE.get(vtype_id, "emergency"))
            vtype.set("speedFactor", "normc(1.2,0.1,1.0,1.4)")  # Drive faster than normal
            vtype.set("speedDev",    "0.1")
            vtype.set("impatience",  "1.0")   # Emergency vehicles are assertive

    # -- Define route elements --
    route_ids: dict = {}
    for direction, moves in ROUTES.items():
        for move, (edge_in, edge_out) in moves.items():
            rid = f"r_{direction}_{move}"
            route_ids[(direction, move)] = rid
            route_elem = ET.SubElement(root, "route")
            route_elem.set("id",    rid)
            route_elem.set("edges", f"{edge_in} {edge_out}")

    # -- Generate regular vehicle departures --
    veh_id   = 0
    vehicles = []

    for direction, intervals in TRAFFIC_VOLUME.items():
        straight_r, left_r, right_r = TURN_RATIO[direction]
        move_choices = ["straight", "left", "right"]
        move_weights = [straight_r, left_r, right_r]

        for t_start, t_end, vol_per_hour in intervals:
            interval_sec = t_end - t_start
            n_veh        = int(vol_per_hour * interval_sec / 3600)

            for _ in range(n_veh):
                depart   = round(random.uniform(t_start, t_end - 1), 2)
                move     = random.choices(move_choices, weights=move_weights)[0]
                vtype_id = random.choices(
                    [v[0] for v in VEHICLE_TYPES],
                    weights=[v[7] for v in VEHICLE_TYPES]
                )[0]
                vehicles.append((depart, direction, move, vtype_id))

    # -- Generate emergency vehicle departures --
    emergency_count = 0
    if EVP_ENABLED and EVP_SPAWN_PROB > 0:
        # Spawn emergency vehicles at random intervals throughout the simulation
        # Expected count: ~1 emergency vehicle per direction per simulation
        directions = ["north", "south", "west", "east"]
        for direction in directions:
            for interval_start in range(0, SIM_DURATION, 900):  # Every 15-minute window
                if random.random() < EVP_SPAWN_PROB * 15:  # Scale probability to 15-min window
                    depart = round(random.uniform(
                        max(interval_start, 60),  # Don't spawn in first 60s
                        min(interval_start + 900, SIM_DURATION - 60)
                    ), 2)
                    move = "straight"  # Emergency vehicles go straight through
                    evtype = random.choices(
                        [v[0] for v in EMERGENCY_VEHICLE_TYPES],
                        weights=[v[7] for v in EMERGENCY_VEHICLE_TYPES]
                    )[0]
                    vehicles.append((depart, direction, move, evtype))
                    emergency_count += 1

    vehicles.sort(key=lambda x: x[0])

    for depart, direction, move, vtype_id in vehicles:
        vehicle = ET.SubElement(root, "vehicle")
        vehicle.set("id",          f"v{veh_id}")
        vehicle.set("type",        vtype_id)
        vehicle.set("route",       route_ids[(direction, move)])
        vehicle.set("depart",      str(depart))
        vehicle.set("departLane",  "best")
        vehicle.set("departSpeed", "random")
        veh_id += 1

    write_xml(os.path.join(BUILD_DIR, "routes.rou.xml"), prettify(root))
    ok(f"Total simulated vehicles: {veh_id} (including {emergency_count} emergency vehicles)")

def build_sensors():
    log.info("[2.5/4] Generating E2 Detector camera sensor definitions...")
    content = """<?xml version="1.0" encoding="UTF-8"?>
<additional>
    <!-- North Sensors -->
    <laneAreaDetector id="cam_N_0" lane="north_in_2_0" pos="0" endPos="-1" freq="1" file="NUL"/>
    <laneAreaDetector id="cam_N_1" lane="north_in_2_1" pos="0" endPos="-1" freq="1" file="NUL"/>
    
    <!-- South Sensors -->
    <laneAreaDetector id="cam_S_0" lane="south_in_2_0" pos="0" endPos="-1" freq="1" file="NUL"/>
    <laneAreaDetector id="cam_S_1" lane="south_in_2_1" pos="0" endPos="-1" freq="1" file="NUL"/>
    
    <!-- West Sensors -->
    <laneAreaDetector id="cam_W_0" lane="west_in_2_0" pos="0" endPos="-1" freq="1" file="NUL"/>
    <laneAreaDetector id="cam_W_1" lane="west_in_2_1" pos="0" endPos="-1" freq="1" file="NUL"/>
    
    <!-- East Sensors -->
    <laneAreaDetector id="cam_E_0" lane="east_in_2_0" pos="0" endPos="-1" freq="1" file="NUL"/>
    <laneAreaDetector id="cam_E_1" lane="east_in_2_1" pos="0" endPos="-1" freq="1" file="NUL"/>
</additional>
"""
    sensor_path = os.path.join(BUILD_DIR, "sensors.add.xml")
    with open(sensor_path, "w", encoding="utf-8") as f:
        f.write(content)
    ok("sensors.add.xml successfully generated")

def build_config():
    log.info("[2.5/3] Generating SUMO configuration config file...")
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">

    <input>
        <net-file value="net.net.xml"/>
        <route-files value="routes.rou.xml"/>
        <additional-files value="sensors.add.xml"/>
    </input>

    <time>
        <begin value="0"/>
        <end value="{SIM_DURATION}"/>
        <step-length value="{STEP_LENGTH}"/>
    </time>

    <processing>
        <ignore-route-errors value="true"/>
        <collision.action value="warn"/>
        <time-to-teleport value="120"/>
        <lanechange.duration value="3"/>
    </processing>

    <random_number>
        <seed value="{RANDOM_SEED}"/>
    </random_number>

    <gui_only>
        <gui-settings-file value="../view.view.xml"/>
        <start value="true"/>
        <quit-on-end value="true"/>
        <tracker-interval value="{STEP_LENGTH}"/>
    </gui_only>

    <output>
        <summary-output value="../../../output/summary.xml"/>
        <tripinfo-output value="../../../output/tripinfo.xml"/>
        <queue-output value="../../../output/queue.xml"/>
    </output>

</configuration>
"""
    os.makedirs("output", exist_ok=True)
    config_path = os.path.join(BUILD_DIR, "config.sumocfg")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    ok("config.sumocfg successfully generated")
    ok("output/ analytics folder prepared")
