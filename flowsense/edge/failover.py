import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)


class EdgeFailoverManager:
    """Manages connection failover for edge nodes.

    P2-6 fixes:
      * The queue dir defaults to a persistent location (not /tmp, which is
        wiped on reboot and would lose queued records).
      * flush_queue rotates the JSONL to a `.sending` file before POSTing, so
        any record written to the live queue *during* a flush is kept (it goes
        to a fresh file) instead of being deleted un-sent.
    """

    def __init__(self, api_url: str, sync_dir: str = "data/sync"):
        self.api_url = api_url
        self.sync_dir = Path(sync_dir)
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.sync_dir / "edge_data.jsonl"
        self.sending_file = self.sync_dir / "edge_data.sending.jsonl"
        self.is_connected = True
        self.sync_queue: List[Dict[str, Any]] = []
        self._background_task: Optional[asyncio.Task] = None
        # Recover any records left mid-flush from a previous run.
        if self.sending_file.exists():
            try:
                self.sending_file.replace(self.queue_file)
            except OSError:
                pass

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
        """Queue data locally in memory and append to JSONL."""
        self.sync_queue.append(data)
        # Append-only; flush rotates this file away, so in-flight flushes never
        # delete records that arrive after the rotation point.
        with open(self.queue_file, "a") as f:
            f.write(json.dumps(data) + "\n")

    async def flush_queue(self):
        """Flush queued records to the API (race-free).

        Rotates the live queue file to a `.sending` copy first, clears the
        in-memory queue, then POSTs. New records arriving during the POST go to
        a brand-new queue file and are flushed on the next cycle. On success the
        `.sending` file is removed; on failure its records are re-queued.
        """
        if not self.sync_queue and not self.queue_file.exists():
            return

        # Rotate: move live file aside so concurrent appends land in a new file.
        if self.queue_file.exists():
            try:
                os.replace(self.queue_file, self.sending_file)
            except OSError as e:
                logger.error(f"Failed to rotate queue file: {e}")
                return

        # Load the batch we are about to send and clear the live queue.
        to_send: List[Dict[str, Any]] = []
        if self.sending_file.exists():
            with open(self.sending_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            to_send.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        self.sync_queue.clear()

        if not to_send:
            if self.sending_file.exists():
                self.sending_file.unlink()
            return

        logger.info(f"Flushing {len(to_send)} records...")
        try:
            async with httpx.AsyncClient() as client:
                for record in to_send:
                    await client.post(f"{self.api_url}/api/v1/detections", json=record)
            logger.info("Flush successful.")
            if self.sending_file.exists():
                self.sending_file.unlink()
        except Exception as e:
            logger.error(f"Failed to flush queue: {e}")
            # Re-queue the unsent batch so the next cycle retries them.
            self.sync_queue.extend(to_send)
            # Re-append to the (new) live file so they persist for the retry.
            with open(self.queue_file, "a") as f:
                for record in to_send:
                    f.write(json.dumps(record) + "\n")
