"""Reconnecting OpenCV video stream wrapper."""
import time

import cv2


class ReconnectingStream:
    """Wraps cv2.VideoCapture; reopens on read failure with backoff."""

    def __init__(self, url: str, max_reconnects: int = 5, backoff: float = 3.0):
        self.url = url
        self.max_reconnects = max_reconnects
        self.backoff = backoff
        self._cap = None

    def open(self):
        cap = cv2.VideoCapture(self.url)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Could not open stream: {self.url}")
        self._cap = cap

    def read(self):
        if self._cap is None:
            self.open()
        attempt = 0
        while True:
            ok, frame = self._cap.read()
            if ok and frame is not None:
                return True, frame
            attempt += 1
            if attempt > self.max_reconnects:
                return False, None
            self._cap.release()
            self._cap = None
            time.sleep(self.backoff)
            try:
                self.open()
            except RuntimeError:
                pass

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
