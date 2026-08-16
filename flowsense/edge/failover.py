import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

class EdgeFailoverManager:
    """Manages connection failover for edge nodes."""

    def __init__(self, api_url: str, sync_dir: str = "/tmp/flowsense/sync"):
        self.api_url = api_url
        self.sync_dir = Path(sync_dir)
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        self.is_connected = True
        self.sync_queue: List[Dict[str, Any]] = []
        self._background_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background health check loop."""
        self._background_task = asyncio.create_task(self._health_check_loop())

    async def stop(self):
        """Stop the background loop."""
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass

    async def _health_check_loop(self):
        while True:
            await self.check_health()
            await asyncio.sleep(10)

    async def check_health(self):
        """Check connection to the central API server."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url}/api/v1/health/", timeout=2.0)
                response.raise_for_status()
            
            if not self.is_connected:
                await self.switch_to_remote()
        except Exception as e:
            if self.is_connected:
                logger.warning(f"Connection lost to API: {e}")
                await self.switch_to_local()

    async def switch_to_local(self):
        """Switch to local-only mode, queueing records."""
        self.is_connected = False
        logger.info("Switched to local mode.")

    async def switch_to_remote(self):
        """Switch to remote mode and flush queued records."""
        self.is_connected = True
        logger.info("Connection restored. Switching to remote mode.")
        await self.flush_queue()

    async def record_data(self, data: Dict[str, Any]):
        """Record data, either sending to API or queuing locally."""
        if self.is_connected:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(f"{self.api_url}/api/v1/detections", json=data)
            except Exception:
                await self._queue_local(data)
        else:
            await self._queue_local(data)

    async def _queue_local(self, data: Dict[str, Any]):
        """Queue data locally in memory and write to JSONL."""
        self.sync_queue.append(data)
        file_path = self.sync_dir / "edge_data.jsonl"
        with open(file_path, "a") as f:
            f.write(json.dumps(data) + "\n")

    async def flush_queue(self):
        """Flush queued records to the API."""
        if not self.sync_queue:
            return
            
        logger.info(f"Flushing {len(self.sync_queue)} records...")
        to_send = self.sync_queue[:]
        self.sync_queue.clear()
        
        try:
             async with httpx.AsyncClient() as client:
                for record in to_send:
                    await client.post(f"{self.api_url}/api/v1/detections", json=record)
             logger.info("Flush successful.")
             file_path = self.sync_dir / "edge_data.jsonl"
             if file_path.exists():
                 file_path.unlink() # Clear the local file on success
        except Exception as e:
             logger.error(f"Failed to flush queue: {e}")
             self.sync_queue.extend(to_send) # Put back in queue
