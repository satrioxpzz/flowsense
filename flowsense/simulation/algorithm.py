"""
SUMO ADAPTIVE TRAFFIC LIGHT ALGORITHM
Pure Logic & Decision-Making Module for Adaptive Control
===================================================================
This module contains pure mathematical formulas, decision state tracking,
and Phase Skipping & Time Extension logic, completely isolated from TraCI.

IMPROVEMENTS OVER ORIGINAL:
  - Dynamic green time scaling based on queue length (Proportional Control)
  - Starvation prevention with accumulated red-time priority weighting
  - Input validation for algorithm parameters
  - Emergency Vehicle Preemption (EVP) decision support
"""

import logging

log = logging.getLogger("flowsense.simulation")


class TimeExtensionAlgorithm:
    def __init__(self, min_green=10.0, max_green=50.0, yellow_duration=4.0,
                 starvation_threshold=120.0, max_queue_capacity=30):
        # --- Input Validation ---
        if min_green <= 0:
            raise ValueError(f"min_green must be > 0, got {min_green}")
        if max_green <= min_green:
            raise ValueError(f"max_green ({max_green}) must be > min_green ({min_green})")
        if yellow_duration <= 0:
            raise ValueError(f"yellow_duration must be > 0, got {yellow_duration}")
        if starvation_threshold <= 0:
            raise ValueError(f"starvation_threshold must be > 0, got {starvation_threshold}")

        self.min_green = min_green
        self.max_green = max_green
        self.yellow_duration = yellow_duration
        self.starvation_threshold = starvation_threshold
        self.max_queue_capacity = max(1, max_queue_capacity)
        
        # Decision state tracking variables
        self.elapsed_green = 0.0
        self.elapsed_yellow = 0.0
        self.is_yellow_phase = False
        self.current_direction = "N"  # Start active from North
        
        # Initial red phase wait trackers per direction
        self.initial_red_wait = {"N": 0.0, "S": 0.0, "E": 0.0, "W": 0.0}

        # Starvation prevention: accumulated red time per direction (seconds)
        self.accumulated_red_time = {"N": 0.0, "S": 0.0, "E": 0.0, "W": 0.0}

        # EVP state tracking
        self.evp_active = False
        self.evp_direction = None
        self.evp_cooldown_remaining = 0.0

    def calculate_dynamic_max_green(self, queue_count: int) -> float:
        """
        Scale the effective max_green proportionally to queue length.
        More vehicles in queue → longer green time allowed (up to max_green).
        Fewer vehicles → shorter green cap (closer to min_green).
        
        Returns:
            Effective maximum green duration in seconds.
        """
        ratio = min(queue_count / self.max_queue_capacity, 1.0)
        return self.min_green + ratio * (self.max_green - self.min_green)

    def decide_yellow_transition(self, step_length: float, vehicles_detected: int | None,
                                  is_healthy: bool, queue_count: int = 0) -> tuple[bool, str]:
        """
        Determines whether the active green phase should transition to yellow
        based on Gap-out (empty gap detected) and Max-out (dynamic maximum limit reached).

        Args:
            step_length: Simulation step length in seconds.
            vehicles_detected: Number of vehicles currently detected by sensors,
                or None when the sensor reading is unavailable (P1-12). None is
                treated as "unknown" — it never triggers a gap-out.
            is_healthy: Whether the camera sensors for this direction are healthy.
            queue_count: Current queue length for dynamic max_green calculation.

        Returns:
            Tuple of (should_transition_to_yellow, reason_string).
        """
        self.elapsed_green += step_length

        # Calculate dynamic max green based on current queue length
        effective_max_green = self.calculate_dynamic_max_green(queue_count)

        if self.elapsed_green >= self.min_green:
            # GAP-OUT: only when the sensor is healthy, a real reading of zero
            # vehicles is present, and no sensor is down for this direction.
            if vehicles_detected == 0 and is_healthy:
                return True, f"GAP-OUT (Empty gap detected after {self.elapsed_green:.1f}s)"
            # MAX-OUT: green reached the dynamic maximum limit.
            elif self.elapsed_green >= effective_max_green:
                return True, f"MAX-OUT (Dynamic green limit of {effective_max_green:.0f}s reached, queue={queue_count})"

        return False, "KEEP"

    def update_starvation_trackers(self, step_length: float, is_dual_mode: bool, direction_phases: dict):
        """
        Increment accumulated red time for all directions currently on red.
        Reset to 0 when a direction goes green.
        Called every simulation tick.
        """
        for direction in ["N", "S", "E", "W"]:
            is_active = (self.current_direction == direction)
            if is_dual_mode:
                is_active = (direction_phases[direction]["green"] == direction_phases[self.current_direction]["green"])
            
            if is_active:
                # Direction is green — reset starvation counter
                self.accumulated_red_time[direction] = 0.0
            else:
                # Direction is red — accumulate wait
                self.accumulated_red_time[direction] += step_length

    def select_next_direction(self, is_dual_mode, direction_phases, counterpart, get_queue_fn):
        """
        Determines the next green phase direction utilizing weighted Phase Skipping logic.
        
        IMPROVEMENT: Instead of strict circular-queue order, uses a weighted priority score:
            score = queue_count * (1 + accumulated_red_time / starvation_threshold)
        This prevents starvation of high-traffic directions.
        """
        sequence = ["N", "E", "S", "W"]
        curr_idx = sequence.index(self.current_direction)
        
        # Collect candidate directions with their weighted scores
        candidates = []
        
        for i in range(1, 5):
            next_idx = (curr_idx + i) % 4
            candidate_dir = sequence[next_idx]
            
            # If in Dual mode, skip candidates sharing the same green phase as the current direction
            if is_dual_mode and direction_phases[candidate_dir]["green"] == direction_phases[self.current_direction]["green"]:
                continue
                
            queue_count = get_queue_fn(candidate_dir)
            if is_dual_mode:
                queue_count += get_queue_fn(counterpart[candidate_dir])
            
            if queue_count > 0:
                # Calculate weighted priority score with starvation bonus
                red_time = self.accumulated_red_time.get(candidate_dir, 0.0)
                if is_dual_mode:
                    red_time = max(red_time, self.accumulated_red_time.get(counterpart[candidate_dir], 0.0))
                
                starvation_weight = 1.0 + (red_time / self.starvation_threshold)
                score = queue_count * starvation_weight
                
                candidates.append((candidate_dir, score, i, queue_count, red_time))
        
        if not candidates:
            # All other directions are completely empty — keep current green
            return self.current_direction
        
        # Sort by weighted score descending (highest priority first)
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_dir, best_score, steps_away, best_queue, best_red_time = candidates[0]
        
        # Log skipped directions
        if steps_away > 1:
            skipped = [sequence[(curr_idx + j) % 4] for j in range(1, steps_away)]
            if is_dual_mode:
                skipped = [d for d in skipped
                          if direction_phases[d]["green"] != direction_phases[self.current_direction]["green"]
                          and direction_phases[d]["green"] != direction_phases[best_dir]["green"]]
            if skipped:
                log.info(f"[SKIP] Phase Skipping active! Skipping empty directions: {', '.join(skipped)}.")
        
        # Log starvation priority if it affected the decision
        if best_red_time > self.starvation_threshold * 0.5:
            log.info(f"[PRIORITY] Direction {best_dir} boosted by starvation weight (red for {best_red_time:.0f}s, score={best_score:.1f}).")
        
        return best_dir

    def handle_evp_request(self, evp_direction: str, cooldown_seconds: float = 10.0) -> bool:
        """
        Handle an Emergency Vehicle Preemption request.
        Forces the algorithm to transition to the requested direction.
        
        Args:
            evp_direction: The direction (N/S/E/W) requiring preemption.
            cooldown_seconds: Cooldown period after preemption.
            
        Returns:
            True if preemption was activated, False if already in cooldown.
        """
        if self.evp_cooldown_remaining > 0:
            return False
        
        self.evp_active = True
        self.evp_direction = evp_direction
        self.evp_cooldown_remaining = cooldown_seconds
        return True

    def tick_evp_cooldown(self, step_length: float):
        """Decrement EVP cooldown timer each step."""
        if self.evp_cooldown_remaining > 0:
            self.evp_cooldown_remaining = max(0.0, self.evp_cooldown_remaining - step_length)

    def calculate_estimated_wait(self, direction, is_dual_mode, direction_phases, counterpart, get_vehicles_fn, get_queue_fn):
        """
        Calculates the real-time estimated remaining wait time for a red light direction.
        """
        if is_dual_mode:
            # In Dual mode, if the target shares the same green phase as the currently active direction, wait time is 0
            if direction_phases[direction]["green"] == direction_phases[self.current_direction]["green"]:
                return 0.0
                
            # If opposite phase, wait time is equal to the remaining active duration of the current phase
            estimated_wait = 0.0
            if self.is_yellow_phase:
                estimated_wait += max(0.0, self.yellow_duration - self.elapsed_yellow)
            else:
                vehicles = get_vehicles_fn(self.current_direction) + get_vehicles_fn(counterpart[self.current_direction])
                
                if self.elapsed_green < self.min_green:
                    estimated_wait += (self.min_green - self.elapsed_green) + self.yellow_duration
                elif vehicles > 0:
                    estimated_wait += max(0.0, self.calculate_dynamic_max_green(get_queue_fn(self.current_direction)) - self.elapsed_green) + self.yellow_duration
                else:
                    estimated_wait += self.yellow_duration
            return estimated_wait

        sequence = ["N", "E", "S", "W"]
        curr_idx = sequence.index(self.current_direction)
        target_idx = sequence.index(direction)
        
        steps_away = (target_idx - curr_idx) % 4
        estimated_wait = 0.0
        
        # Calculate remaining active time of current active phase (Green/Yellow)
        if self.is_yellow_phase:
            estimated_wait += max(0.0, self.yellow_duration - self.elapsed_yellow)
        else:
            vehicles = get_vehicles_fn(self.current_direction)
                
            if self.elapsed_green < self.min_green:
                estimated_wait += (self.min_green - self.elapsed_green) + self.yellow_duration
            elif vehicles > 0:
                estimated_wait += max(0.0, self.max_green - self.elapsed_green) + self.yellow_duration
            else:
                estimated_wait += self.yellow_duration  # Immediate yellow transition
                
        # Add min_green + yellow for intermediate directions containing queued traffic (non-skipped)
        for i in range(1, steps_away):
            intermediate_idx = (curr_idx + i) % 4
            intermediate_dir = sequence[intermediate_idx]
            
            if get_queue_fn(intermediate_dir) > 0:
                estimated_wait += self.min_green + self.yellow_duration
                
        return estimated_wait

    def get_timer_text(self, direction, is_dual_mode, direction_phases, counterpart, get_vehicles_fn, get_queue_fn):
        """
        Dynamically calculates active/red phase durations for SUMO GUI text visualization.
        """
        # 1. If target direction is currently active (Green or Yellow)
        is_active = (self.current_direction == direction)
        if is_dual_mode:
            is_active = (direction_phases[direction]["green"] == direction_phases[self.current_direction]["green"])
            
        if is_active:
            if self.is_yellow_phase:
                rem = max(0.0, self.yellow_duration - self.elapsed_yellow)
                return f"Yellow: {int(rem)}s/{int(self.yellow_duration)}s"
            else:
                # Show countdown to maximum allowed green duration
                rem = max(0.0, self.max_green - self.elapsed_green)
                return f"Green: {int(rem)}s/{int(self.max_green)}s"
        
        # 2. If target direction is currently Red (show dynamic real-time wait estimation)
        rem = self.calculate_estimated_wait(direction, is_dual_mode, direction_phases, counterpart, get_vehicles_fn, get_queue_fn)
        total = self.initial_red_wait.get(direction, 0.0)
        
        # Visual failsafe: Ensure wait total is never less than remaining countdown wait time
        if rem > total:
            self.initial_red_wait[direction] = rem
            total = rem
            
        return f"Red: {int(rem)}s/{int(total)}s"
