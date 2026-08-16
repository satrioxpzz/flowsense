import os
import time
import logging
import threading
from pathlib import Path
from .garage import GarageStorageClient

logger = logging.getLogger(__name__)

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
        """Sync only detection data (JSONL)."""
        logger.info("Syncing detections...")
        self.client.ensure_bucket()
        data_path = Path(self.data_dir)
        if data_path.exists():
            for file in data_path.glob("*.jsonl"):
                remote_key = f"detections/{file.name}"
                self.client.upload_file(str(file), remote_key)

    def sync_models(self):
        """Sync only model weights."""
        logger.info("Syncing models...")
        self.client.ensure_bucket()
        if os.path.exists(self.model_path):
            remote_key = f"models/{os.path.basename(self.model_path)}"
            self.client.upload_file(self.model_path, remote_key)

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
