import os
import time
import logging
import threading
from datetime import datetime
from pathlib import Path
from .garage import GarageStorageClient

logger = logging.getLogger(__name__)

# Files modified more recently than this are still being written by the edge
# connector and are skipped on this sync cycle (P2-7). They will be uploaded
# once they cool down, or after daily rotation.
_ACTIVE_GRACE_SECONDS = 300


class FlowSenseSyncManager:
    """Manages synchronization of FlowSense data to Garage storage."""
    def __init__(self, data_dir: str = "data", model_path: str = "yolo11n.pt", config_dir: str = "."):
        self.client = GarageStorageClient()
        self.data_dir = data_dir
        self.model_path = model_path
        self.config_dir = config_dir
        self.running = False
        self.thread = None

    def sync_detections(self):
        """Sync only detection data (JSONL).

        P2-7: the live connector file grows continuously, so re-uploading it in
        full every cycle is O(n^2) bandwidth. We only upload files that are not
        actively being written (older than _ACTIVE_GRACE_SECONDS) — i.e. rotated
        / closed files. The hot file is uploaded once it cools or after rotation.
        """
        logger.info("Syncing detections...")
        self.client.ensure_bucket()
        data_path = Path(self.data_dir)
        now = time.time()
        if data_path.exists():
            for file in data_path.glob("*.jsonl"):
                try:
                    mtime = file.stat().st_mtime
                except OSError:
                    continue
                if now - mtime < _ACTIVE_GRACE_SECONDS:
                    # Still being written by the connector; skip this cycle.
                    continue
                remote_key = f"detections/{file.name}"
                self.client.upload_file(str(file), remote_key)

    def sync_models(self):
        """Sync only model weights."""
        logger.info("Syncing models...")
        self.client.ensure_bucket()
        if os.path.exists(self.model_path):
            remote_key = f"models/{os.path.basename(self.model_path)}"
            self.client.upload_file(self.model_path, remote_key)

    def rotate_detections(self):
        """Rotate active detection files into date-stamped, closed copies.

        Renames `connector_30.jsonl` -> `connector_30.2026-08-16.jsonl` so the
        previous day's data becomes a closed file that `sync_detections` will
        upload in full exactly once (P2-7). The edge connector keeps appending
        to the fresh, empty live file afterwards.
        """
        data_path = Path(self.data_dir)
        if not data_path.exists():
            return
        stamp = datetime.now().strftime("%Y-%m-%d")
        for file in data_path.glob("connector_*.jsonl"):
            rotated = data_path / f"{file.stem}.{stamp}.jsonl"
            try:
                if file.stat().st_size == 0:
                    continue
                file.replace(rotated)
            except OSError as e:
                logger.warning("detection rotation failed for %s: %s", file, e)

    def sync_configs(self):
        """Sync only NON-SECRET config files.

        Security: never upload .env or any file that may contain credentials.
        Only ship calibration / scenario configs that are safe to persist in
        object storage (rois.json, simulation_config.toml, etc.).
        """
        logger.info("Syncing configs...")
        self.client.ensure_bucket()
        config_files = ["rois.json", "simulation_config.toml", "config.json", "config.yaml"]
        for config in config_files:
            config_path = os.path.join(self.config_dir, config)
            if os.path.exists(config_path):
                remote_key = f"configs/{config}"
                self.client.upload_file(config_path, remote_key)

    def sync_now(self):
        """Immediate full sync."""
        self.sync_configs()
        self.sync_models()
        self.sync_detections()

    def _sync_loop(self, interval_seconds: int):
        while self.running:
            try:
                self.sync_now()
            except Exception as e:
                logger.exception("Sync loop error")
            time.sleep(interval_seconds)

    def start_sync(self, interval_seconds: int = 300):
        """Start background sync loop."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._sync_loop, args=(interval_seconds,), daemon=True)
        self.thread.start()
        logger.info(f"Started sync loop with interval {interval_seconds}s")

    def stop_sync(self):
        """Stop background sync."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        logger.info("Stopped sync loop")
