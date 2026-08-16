"""TraCI bridge between SUMO simulator and adaptive decision logic.

Reads E2 detector camera sensors and delegates traffic light decision-making
to TimeExtensionAlgorithm. All traci imports are lazy so unit tests run
without SUMO installed.
"""

import logging
import math

from .algorithm import TimeExtensionAlgorithm
from .sim_config import (
    MIN_GREEN, MAX_GREEN, YELLOW_DURATION, STARVATION_THRESHOLD, MAX_QUEUE_CAPACITY,
    EVP_ENABLED, EVP_DETECTION_RADIUS, EVP_COOLDOWN,
    LOG_ENABLED, LOG_INTERVAL_STEPS, LOG_OUTPUT_FILE,
)

log = logging.getLogger("flowsense.simulation")


class TimeExtensionController:
    def __init__(self, tls_id="center", min_green=None, max_green=None,
                 yellow_duration=None, enable_evp=None, enable_logging=None):
        import traci
        self._traci = traci

        self.tls_id = tls_id

        _min_green = min_green if min_green is not None else MIN_GREEN
        _max_green = max_green if max_green is not None else MAX_GREEN
        _yellow_dur = yellow_duration if yellow_duration is not None else YELLOW_DURATION
        _evp_enabled = enable_evp if enable_evp is not None else EVP_ENABLED
        _log_enabled = enable_logging if enable_logging is not None else LOG_ENABLED

        self.algorithm = TimeExtensionAlgorithm(
            min_green=_min_green,
            max_green=_max_green,
            yellow_duration=_yellow_dur,
            starvation_threshold=STARVATION_THRESHOLD,
            max_queue_capacity=MAX_QUEUE_CAPACITY,
        )

        self.cams_healthy = {"N": True, "S": True, "E": True, "W": True}
        self.counterpart = {"N": "S", "S": "N", "E": "W", "W": "E"}
        self.is_dual_mode = False

        self.evp_enabled = _evp_enabled
        self.evp_direction_map = {}

        try:
            logics = traci.trafficlight.getAllProgramLogics(self.tls_id)
            if logics:
                num_phases = len(logics[0].phases)
                if num_phases <= 4:
                    self.is_dual_mode = True
        except Exception as e:
            log.warning("Failed to dynamically detect TLS program: %s", e)

        if self.is_dual_mode:
            self.direction_phases = {
                "N": {"green": 0, "yellow": 1},
                "S": {"green": 0, "yellow": 1},
                "E": {"green": 2, "yellow": 3},
                "W": {"green": 2, "yellow": 3}
            }
            log.info("TLS Detection: Dual mode (opposites) automatically detected.")
        else:
            self.direction_phases = {
                "S": {"green": 0, "yellow": 1},
                "E": {"green": 2, "yellow": 3},
                "N": {"green": 4, "yellow": 5},
                "W": {"green": 6, "yellow": 7}
            }
            log.info("TLS Detection: Single mode (incoming) automatically detected.")

        self.cams = {
            "N": ["cam_N_0", "cam_N_1"],
            "S": ["cam_S_0", "cam_S_1"],
            "W": ["cam_W_0", "cam_W_1"],
            "E": ["cam_E_0", "cam_E_1"]
        }

        try:
            traci.trafficlight.setPhase(self.tls_id, self.direction_phases[self.algorithm.current_direction]["green"])
            traci.trafficlight.setPhaseDuration(self.tls_id, 9999.0)
        except Exception as e:
            log.warning("Failed to initialize TLS: %s", e)

        try:
            cx, cy = traci.junction.getPosition(self.tls_id)
        except Exception:
            cx, cy = 400.0, 400.0

        self.junction_pos = (cx, cy)

        self.poi_positions = {
            "timer_N": (cx + 10.0, cy + 30.0),
            "timer_S": (cx - 10.0, cy - 30.0),
            "timer_W": (cx - 30.0, cy + 10.0),
            "timer_E": (cx + 30.0, cy - 10.0)
        }

        for poi_id, (px, py) in self.poi_positions.items():
            try:
                traci.poi.add(poi_id, x=px, y=py, color=(0, 0, 0, 255), poiType="0", width=0.1, height=0.1)
            except Exception:
                pass

        if self.evp_enabled:
            self._build_evp_direction_map()
            log.info("Emergency Vehicle Preemption (EVP): ENABLED")

        # Health recovery (P1-12): a momentary sensor error sets
        # cams_healthy[dir]=False, but it must not permanently degrade a
        # direction. We count consecutive *successful* reads while down and
        # restore health after a few clean samples.
        self._health_down_steps = {d: 0 for d in ["N", "S", "E", "W"]}
        self._health_recovery_threshold = 5

        self.logger = None
        if _log_enabled:
            try:
                from .sim_logger import SimulationLogger
                self.logger = SimulationLogger(
                    output_path=LOG_OUTPUT_FILE,
                    interval_steps=LOG_INTERVAL_STEPS,
                )
            except Exception as e:
                log.warning("Failed to initialize logger: %s", e)

    def _build_evp_direction_map(self):
        """Build a mapping from incoming edge IDs to compass directions for EVP detection."""
        self.evp_direction_map = {
            "north_in_1": "N", "north_in_2": "N",
            "south_in_1": "S", "south_in_2": "S",
            "west_in_1": "W", "west_in_2": "W",
            "east_in_1": "E", "east_in_2": "E",
        }

    def detect_emergency_vehicles(self) -> str | None:
        """Scan all active vehicles for emergency types approaching the junction."""
        if not self.evp_enabled:
            return None

        traci = self._traci
        try:
            cx, cy = self.junction_pos
            nearest_dist = float("inf")
            nearest_direction = None

            for veh_id in traci.vehicle.getIDList():
                vtype = traci.vehicle.getTypeID(veh_id)
                if vtype not in ("ambulance", "fire_truck"):
                    continue

                vx, vy = traci.vehicle.getPosition(veh_id)
                dist = math.sqrt((vx - cx) ** 2 + (vy - cy) ** 2)

                if dist < EVP_DETECTION_RADIUS and dist < nearest_dist:
                    edge_id = traci.vehicle.getRoadID(veh_id)
                    direction = self.evp_direction_map.get(edge_id)
                    if direction:
                        nearest_dist = dist
                        nearest_direction = direction

            return nearest_direction

        except Exception:
            return None

    def step(self, step_length=0.1):
        """Executed at every 0.1s step in main execution loop."""
        traci = self._traci

        # Health recovery (P1-12): if a direction was marked unhealthy, probe it
        # each tick. After several consecutive clean reads, restore its health so
        # a transient glitch does not permanently degrade the direction.
        self._attempt_health_recovery()

        self.update_gui_pois()
        self.algorithm.update_starvation_trackers(step_length, self.is_dual_mode, self.direction_phases)
        self.algorithm.tick_evp_cooldown(step_length)

        # --- Emergency Vehicle Preemption Check ---
        if self.evp_enabled and not self.algorithm.evp_active:
            evp_dir = self.detect_emergency_vehicles()
            if evp_dir:
                is_already_green = (self.algorithm.current_direction == evp_dir)
                if self.is_dual_mode:
                    is_already_green = (self.direction_phases[evp_dir]["green"] ==
                                       self.direction_phases[self.algorithm.current_direction]["green"])

                if not is_already_green:
                    activated = self.algorithm.handle_evp_request(evp_dir, EVP_COOLDOWN)
                    if activated:
                        log.info("EVP: Emergency vehicle detected approaching %s! Preempting traffic signal.", evp_dir)

                        if self.logger:
                            self.logger.record_event(f"EVP-PREEMPT direction={evp_dir}")

                        self.algorithm.is_yellow_phase = True
                        self.algorithm.elapsed_yellow = 0.0
                        self.algorithm.evp_active = True

                        traci.trafficlight.setPhase(self.tls_id, self.direction_phases[self.algorithm.current_direction]["yellow"])
                        traci.trafficlight.setPhaseDuration(self.tls_id, 9999.0)
                        return

        # --- Log step data ---
        if self.logger:
            try:
                sim_time = traci.simulation.getTime()
                phase = "Yellow" if self.algorithm.is_yellow_phase else "Green"
                queues = {d: self.get_queue_count(d) for d in ["N", "S", "E", "W"]}
                vehicles = {d: self.get_active_vehicles(d) for d in ["N", "S", "E", "W"]}
                self.logger.log_step(
                    sim_time=sim_time,
                    phase=phase,
                    active_direction=self.algorithm.current_direction,
                    queues=queues,
                    vehicles=vehicles,
                    elapsed_green=self.algorithm.elapsed_green,
                )
            except Exception:
                pass

        # 1. If currently in transition Yellow phase
        if self.algorithm.is_yellow_phase:
            self.algorithm.elapsed_yellow += step_length
            if self.algorithm.elapsed_yellow >= self.algorithm.yellow_duration:
                self.algorithm.is_yellow_phase = False
                self.algorithm.elapsed_yellow = 0.0
                self.algorithm.elapsed_green = 0.0

                if self.algorithm.evp_active and self.algorithm.evp_direction:
                    next_dir = self.algorithm.evp_direction
                    self.algorithm.evp_active = False
                    self.algorithm.evp_direction = None
                    log.info("EVP: Preemptive GREEN activated for direction %s!", next_dir)

                    if self.logger:
                        self.logger.record_event(f"EVP-GREEN direction={next_dir}")
                else:
                    next_dir = self.algorithm.select_next_direction(
                        self.is_dual_mode, self.direction_phases, self.counterpart, self.get_queue_count
                    )

                old_dir = self.algorithm.current_direction
                self.algorithm.current_direction = next_dir

                self.algorithm.initial_red_wait[old_dir] = self.algorithm.calculate_estimated_wait(
                    old_dir, self.is_dual_mode, self.direction_phases, self.counterpart,
                    self.get_active_vehicles, self.get_queue_count
                )

                traci.trafficlight.setPhase(self.tls_id, self.direction_phases[next_dir]["green"])
                traci.trafficlight.setPhaseDuration(self.tls_id, 9999.0)
                log.info("GREEN light active in direction %s (min_green=%ss)", next_dir, self.algorithm.min_green)
            return

        # 2. If in active Green phase, fetch sensor counts and query decision transition
        vehicles_detected = self.get_active_vehicles(self.algorithm.current_direction)
        queue_count = self.get_queue_count(self.algorithm.current_direction)

        if self.is_dual_mode:
            counter_detected = self.get_active_vehicles(self.counterpart[self.algorithm.current_direction])
            counter_queue = self.get_queue_count(self.counterpart[self.algorithm.current_direction])
            # Combine only known (non-None) readings. If a sensor is down we keep
            # the other direction's value instead of poisoning the sum with a
            # sentinel (P1-12).
            if vehicles_detected is not None and counter_detected is not None:
                vehicles_detected = vehicles_detected + counter_detected
            elif counter_detected is not None:
                vehicles_detected = counter_detected
            if queue_count is not None and counter_queue is not None:
                queue_count = queue_count + counter_queue
            elif counter_queue is not None:
                queue_count = counter_queue

        is_healthy = self.cams_healthy[self.algorithm.current_direction]
        if self.is_dual_mode:
            is_healthy = is_healthy and self.cams_healthy[self.counterpart[self.algorithm.current_direction]]

        should_yellow, reason = self.algorithm.decide_yellow_transition(
            step_length, vehicles_detected, is_healthy, queue_count
        )

        if should_yellow:
            self.algorithm.is_yellow_phase = True
            self.algorithm.elapsed_yellow = 0.0

            traci.trafficlight.setPhase(self.tls_id, self.direction_phases[self.algorithm.current_direction]["yellow"])
            traci.trafficlight.setPhaseDuration(self.tls_id, 9999.0)

            log.info("Transitioning to Yellow for direction %s due to %s.", self.algorithm.current_direction, reason)

            if self.logger:
                self.logger.record_event(reason)

    def get_active_vehicles(self, direction):
        """Reads active vehicle count from lane area detectors.

        Returns None (not a sentinel number) when the sensor is unhealthy or
        errors, so the value can never leak into arithmetic as if it were a real
        vehicle count (P1-12). Callers must treat None as "unknown".
        """
        traci = self._traci
        if not self.cams_healthy[direction]:
            return None

        try:
            active_cams = self.cams[direction]
            return sum(traci.lanearea.getLastStepVehicleNumber(cam) for cam in active_cams)
        except Exception:
            log.error("FAILSAFE: Camera for direction '%s' detected ERROR! Activating fixed-time fallback.", direction)
            self.cams_healthy[direction] = False
            return None

    def get_queue_count(self, direction):
        """Reads total queued vehicle length from lane area detectors.

        Returns None when the sensor is unhealthy or errors (P1-12).
        """
        traci = self._traci
        if not self.cams_healthy[direction]:
            return None

        try:
            candidate_cams = self.cams[direction]
            return sum(traci.lanearea.getJamLengthVehicle(cam) for cam in candidate_cams)
        except Exception:
            log.error("FAILSAFE: Camera for direction '%s' detected ERROR! Activating fixed-time fallback.", direction)
            self.cams_healthy[direction] = False
            return None

    def _attempt_health_recovery(self):
        """Restore sensor health after a transient failure (P1-12).

        A direction flagged unhealthy is probed each tick. If it returns a clean
        reading a few times in a row, its health is restored -- so a momentary
        glitch does not permanently degrade that direction (the original bug
        where cams_healthy[dir]=False was never reverted).
        """
        traci = self._traci
        for direction in ["N", "S", "E", "W"]:
            if self.cams_healthy[direction]:
                self._health_down_steps[direction] = 0
                continue
            try:
                ok = all(
                    traci.lanearea.getLastStepVehicleNumber(cam) >= 0
                    for cam in self.cams[direction]
                )
            except Exception:
                ok = False
            if ok:
                self._health_down_steps[direction] += 1
                if self._health_down_steps[direction] >= self._health_recovery_threshold:
                    self.cams_healthy[direction] = True
                    self._health_down_steps[direction] = 0
                    log.info("Sensor for direction '%s' recovered; health restored.", direction)
            else:
                self._health_down_steps[direction] = 0

    def update_gui_pois(self):
        """Refreshes countdown timers and vehicle queue length texts in SUMO GUI."""
        traci = self._traci
        for poi_id in self.poi_positions.keys():
            dir_key = poi_id.split("_")[1]

            timer_text = self.algorithm.get_timer_text(
                dir_key, self.is_dual_mode, self.direction_phases, self.counterpart,
                self.get_active_vehicles, self.get_queue_count
            )

            try:
                if not self.cams_healthy[dir_key]:
                    count = 0
                else:
                    count = sum(traci.lanearea.getJamLengthVehicle(cam) for cam in self.cams[dir_key])
            except Exception:
                count = 0

            combined_text = f"[{timer_text} | Queue: {count}]"
            try:
                traci.poi.setType(poi_id, combined_text)
            except Exception:
                pass

    def finalize(self):
        """Clean up resources at simulation end."""
        if self.logger:
            self.logger.finalize()


class FixedTimeController:
    """Passive controller that displays countdown timers for SUMO's built-in fixed-time TLS program.
    Does NOT override or modify any traffic light phases — purely read-only GUI overlay."""

    def __init__(self, tls_id="center", enable_logging=None):
        import traci
        self._traci = traci

        self.tls_id = tls_id
        _log_enabled = enable_logging if enable_logging is not None else LOG_ENABLED

        try:
            logics = traci.trafficlight.getAllProgramLogics(self.tls_id)
            self.phases = logics[0].phases if logics else []
        except Exception as e:
            log.warning("Failed to read TLS program: %s", e)
            self.phases = []

        self.num_phases = len(self.phases)

        self.direction_links = {"N": [], "S": [], "E": [], "W": []}
        try:
            controlled = traci.trafficlight.getControlledLinks(self.tls_id)
            for idx, links in enumerate(controlled):
                if links:
                    incoming_lane = links[0][0]
                    if "north" in incoming_lane:
                        self.direction_links["N"].append(idx)
                    elif "south" in incoming_lane:
                        self.direction_links["S"].append(idx)
                    elif "east" in incoming_lane:
                        self.direction_links["E"].append(idx)
                    elif "west" in incoming_lane:
                        self.direction_links["W"].append(idx)
        except Exception as e:
            log.warning("Failed to read TLS links: %s", e)

        self._total_red_cache = {}
        for d in ["N", "S", "E", "W"]:
            self._total_red_cache[d] = self._calculate_total_red(d)

        self.cams = {
            "N": ["cam_N_0", "cam_N_1"],
            "S": ["cam_S_0", "cam_S_1"],
            "W": ["cam_W_0", "cam_W_1"],
            "E": ["cam_E_0", "cam_E_1"]
        }

        try:
            cx, cy = traci.junction.getPosition(self.tls_id)
        except Exception:
            cx, cy = 400.0, 400.0

        self.poi_positions = {
            "timer_N": (cx + 10.0, cy + 30.0),
            "timer_S": (cx - 10.0, cy - 30.0),
            "timer_W": (cx - 30.0, cy + 10.0),
            "timer_E": (cx + 30.0, cy - 10.0)
        }

        for poi_id, (px, py) in self.poi_positions.items():
            try:
                traci.poi.add(poi_id, x=px, y=py, color=(0, 0, 0, 255), poiType="0", width=0.1, height=0.1)
            except Exception:
                pass

        self.logger = None
        if _log_enabled:
            try:
                from .sim_logger import SimulationLogger
                self.logger = SimulationLogger(
                    output_path=LOG_OUTPUT_FILE.replace(".csv", "_fixed.csv"),
                    interval_steps=LOG_INTERVAL_STEPS,
                )
            except Exception as e:
                log.warning("Failed to initialize logger: %s", e)

        log.info("Fixed-time TLS: Countdown timer overlay active (read-only, no phase override).")

    def step(self, step_length=0.1):
        """Read SUMO's current TLS state and refresh POI countdown labels each tick."""
        traci = self._traci
        self._update_gui_pois()

        if self.logger:
            try:
                sim_time = traci.simulation.getTime()
                current_phase_idx = traci.trafficlight.getPhase(self.tls_id)
                current_state = self.phases[current_phase_idx].state if current_phase_idx < self.num_phases else ""

                active_dir = "?"
                for d in ["N", "S", "E", "W"]:
                    if self._is_green_in_state(current_state, d):
                        active_dir = d
                        break

                phase_label = "Green"
                for d in ["N", "S", "E", "W"]:
                    if self._is_yellow_in_state(current_state, d):
                        phase_label = "Yellow"
                        break

                queues = {}
                vehicles = {}
                for d in ["N", "S", "E", "W"]:
                    try:
                        queues[d] = sum(traci.lanearea.getJamLengthVehicle(cam) for cam in self.cams[d])
                        vehicles[d] = sum(traci.lanearea.getLastStepVehicleNumber(cam) for cam in self.cams[d])
                    except Exception:
                        queues[d] = 0
                        vehicles[d] = 0

                self.logger.log_step(
                    sim_time=sim_time,
                    phase=phase_label,
                    active_direction=active_dir,
                    queues=queues,
                    vehicles=vehicles,
                    elapsed_green=0.0,
                )
            except Exception:
                pass

    def _is_green_in_state(self, state_string, direction):
        for idx in self.direction_links[direction]:
            if idx < len(state_string) and state_string[idx] in ('G', 'g'):
                return True
        return False

    def _is_yellow_in_state(self, state_string, direction):
        for idx in self.direction_links[direction]:
            if idx < len(state_string) and state_string[idx] in ('y', 'Y'):
                return True
        return False

    def _calculate_total_red(self, direction):
        if self.num_phases == 0:
            return 0.0

        green_idx = None
        for i in range(self.num_phases):
            if self._is_green_in_state(self.phases[i].state, direction):
                green_idx = i
                break

        if green_idx is None:
            return sum(p.duration for p in self.phases)

        last_active_idx = green_idx
        idx = (green_idx + 1) % self.num_phases
        while idx != green_idx:
            s = self.phases[idx].state
            if self._is_green_in_state(s, direction) or self._is_yellow_in_state(s, direction):
                last_active_idx = idx
                idx = (idx + 1) % self.num_phases
            else:
                break

        total = 0.0
        idx = (last_active_idx + 1) % self.num_phases
        while idx != green_idx:
            total += self.phases[idx].duration
            idx = (idx + 1) % self.num_phases

        return total

    def _get_timer_text(self, direction):
        traci = self._traci
        try:
            current_phase_idx = traci.trafficlight.getPhase(self.tls_id)
            next_switch = traci.trafficlight.getNextSwitch(self.tls_id)
            sim_time = traci.simulation.getTime()
            time_remaining = max(0.0, next_switch - sim_time)
            current_state = self.phases[current_phase_idx].state if current_phase_idx < self.num_phases else ""
            phase_dur = self.phases[current_phase_idx].duration if current_phase_idx < self.num_phases else 0
        except Exception:
            return "N/A"

        if self._is_green_in_state(current_state, direction):
            return f"Green: {int(time_remaining)}s/{int(phase_dur)}s"
        elif self._is_yellow_in_state(current_state, direction):
            return f"Yellow: {int(time_remaining)}s/{int(phase_dur)}s"
        else:
            wait = time_remaining
            idx = (current_phase_idx + 1) % self.num_phases
            for _ in range(self.num_phases):
                if self._is_green_in_state(self.phases[idx].state, direction):
                    break
                wait += self.phases[idx].duration
                idx = (idx + 1) % self.num_phases

            total_red = self._total_red_cache.get(direction, 0.0)
            return f"Red: {int(wait)}s/{int(total_red)}s"

    def _update_gui_pois(self):
        traci = self._traci
        for poi_id in self.poi_positions.keys():
            dir_key = poi_id.split("_")[1]
            timer_text = self._get_timer_text(dir_key)

            try:
                count = sum(traci.lanearea.getJamLengthVehicle(cam) for cam in self.cams[dir_key])
            except Exception:
                count = 0

            combined_text = f"[{timer_text} | Queue: {count}]"
            try:
                traci.poi.setType(poi_id, combined_text)
            except Exception:
                pass

    def finalize(self):
        """Clean up resources at simulation end."""
        if self.logger:
            self.logger.finalize()
