import json
import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OverrideState(Enum):
    MANUAL_ALL_RED = "MANUAL_ALL_RED"
    MANUAL_FLASH = "MANUAL_FLASH"
    MANUAL_GREEN_PHASE = "MANUAL_GREEN_PHASE"
    AUTO = "AUTO"


class ManualOverrideController:
    """Manages manual overrides for traffic signals.

    P2-5 fixes:
      * A `threading.Lock` guards all shared state (this is a real concurrency
        primitive for live traffic-light control, not a toy).
      * `get_status()` is now a pure read — it no longer mutates state as a
        side effect (the auto-revert on lock expiry moved to `_revert_if_expired`,
        called from the mutating methods / a periodic tick).
      * The audit log is persisted to disk (append-only JSONL) so it survives
        restarts — required for compliance on a real signal override.
    """

    def __init__(self, timeout_seconds: int = 3600,
                 audit_log_path: Optional[str] = None):
        self.state = OverrideState.AUTO
        self.active_phase: Optional[int] = None
        self.lock_owner: Optional[str] = None
        self.lock_expiry: float = 0
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._audit_log: List[Dict] = []
        self._audit_path = Path(audit_log_path) if audit_log_path else None
        if self._audit_path:
            try:
                self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("audit log dir unavailable: %s", e)

    def _is_locked(self, now: float) -> bool:
        return self.lock_owner is not None and now < self.lock_expiry

    def _revert_if_expired(self, now: Optional[float] = None):
        """Revert to AUTO if the lock has expired. Caller must hold the lock."""
        now = now if now is not None else time.time()
        if self.state != OverrideState.AUTO and not self._is_locked(now):
            self.state = OverrideState.AUTO
            self.active_phase = None
            self.lock_owner = None
            self._log_audit("system", "AUTO_REVERT", {"reason": "lock_expired"})

    def lock(self, user: str) -> bool:
        """Lock the controller for manual override."""
        now = time.time()
        with self._lock:
            if self.lock_owner and self.lock_owner != user and now < self.lock_expiry:
                logger.warning(f"Lock denied for {user}: locked by {self.lock_owner}")
                return False

            self.lock_owner = user
            self.lock_expiry = now + self.timeout_seconds
            self._log_audit(user, "LOCK", {"timeout": self.timeout_seconds})
            return True

    def unlock(self, user: str) -> bool:
        """Unlock the controller, reverting to AUTO."""
        with self._lock:
            if self.lock_owner != user and self.lock_owner is not None:
                logger.warning(f"Unlock denied for {user}: locked by {self.lock_owner}")
                return False

            self.lock_owner = None
            self.lock_expiry = 0
            self.state = OverrideState.AUTO
            self.active_phase = None
            self._log_audit(user, "UNLOCK", {})
            return True

    def set_override(self, user: str, state: OverrideState, phase: Optional[int] = None) -> bool:
        """Set a manual override state."""
        now = time.time()
        with self._lock:
            if self.lock_owner != user:
                logger.warning(f"Override denied for {user}: not lock owner")
                return False

            if now > self.lock_expiry:
                logger.warning(f"Override denied for {user}: lock expired")
                self.unlock(user)
                return False

            if state == OverrideState.MANUAL_GREEN_PHASE and phase is None:
                logger.error("Phase must be specified for MANUAL_GREEN_PHASE")
                return False

            self.state = state
            self.active_phase = phase if state == OverrideState.MANUAL_GREEN_PHASE else None

            self._log_audit(user, "SET_OVERRIDE", {"state": state.value, "phase": phase})
            # Reset timeout on activity
            self.lock_expiry = time.time() + self.timeout_seconds
            return True

    def tick(self):
        """Periodic housekeeping: revert to AUTO if the lock expired."""
        with self._lock:
            self._revert_if_expired()

    def get_status(self) -> Dict:
        """Get the current controller status (pure read, no side effects)."""
        with self._lock:
            now = time.time()
            is_locked = self._is_locked(now)
            return {
                "state": self.state.value,
                "active_phase": self.active_phase,
                "is_locked": is_locked,
                "lock_owner": self.lock_owner,
                "time_remaining": max(0, int(self.lock_expiry - now)) if is_locked else 0,
            }

    def get_audit_log(self) -> List[Dict]:
        with self._lock:
            return list(self._audit_log)

    def _log_audit(self, user: str, action: str, details: Dict):
        """Record an audit log entry (in-memory + persisted to disk)."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user,
            "action": action,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"AUDIT: {entry}")
        if self._audit_path:
            try:
                with open(self._audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError as e:
                logger.warning("failed to persist audit log: %s", e)
