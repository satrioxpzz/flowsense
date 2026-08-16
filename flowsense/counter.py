"""Unique per-track, per-lane crossing counting.

The ``_seen`` set is bounded: a long-running process (days of uptime) would
otherwise accumulate one entry per ``(track_id, lane)`` forever (P1-11). We cap
it with a FIFO eviction so memory stays bounded while still suppressing duplicate
counts for tracks that remain live.
"""

from collections import OrderedDict, defaultdict
from typing import Dict, List, Optional, Tuple

# Hard cap on remembered (track_id, lane) pairs. Once exceeded, the oldest
# entries are evicted. Crossings counters are NOT reset by eviction — a track
# that disappears and reappears after eviction may be counted again, which is
# the correct, bounded behaviour (a rare, harmless double-count vs. an
# unbounded memory leak).
MAX_SEEN = 200_000


class TrackingCounter:
    """Counts each tracked vehicle once per lane it crosses."""

    def __init__(self, max_seen: int = MAX_SEEN):
        self.crossings: Dict[str, int] = defaultdict(int)
        self._seen: "OrderedDict[Tuple[int, Optional[str]], None]" = OrderedDict()
        self._max_seen = max_seen

    def update(self, tracked_dets: List[Tuple[int, Optional[str]]]) -> Dict[str, int]:
        for track_id, lane in tracked_dets:
            if lane is None:
                continue
            key = (track_id, lane)
            if key not in self._seen:
                self._seen[key] = None
                self._seen.move_to_end(key)
                self.crossings[lane] += 1
                # Evict oldest if over the cap.
                while len(self._seen) > self._max_seen:
                    self._seen.popitem(last=False)
        return self.snapshot()

    def snapshot(self) -> Dict[str, int]:
        return dict(self.crossings)

    def reset(self):
        self.crossings = defaultdict(int)
        self._seen = OrderedDict()
