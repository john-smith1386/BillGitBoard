"""Small thread-safe sliding-window limiter for analysis requests."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(0, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._next_sweep = 0.0

    def _sweep_unlocked(self, current: float) -> None:
        """Drop keys whose newest event has aged out of the window.

        Without this the map grows once per distinct source address and never
        shrinks, which for a public service means a slow leak that anyone with
        a wide address range can drive. Sweeping once per window keeps the cost
        proportional to the live key count rather than to request volume.
        """

        if current < self._next_sweep:
            return
        self._next_sweep = current + self.window_seconds
        cutoff = current - self.window_seconds
        stale = [key for key, events in self._events.items() if not events or events[-1] <= cutoff]
        for key in stale:
            del self._events[key]

    def consume(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        """Consume one request and return ``(allowed, retry_after_seconds)``."""

        if self.limit == 0:
            return True, 0
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            self._sweep_unlocked(current)
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry = max(1, math.ceil(events[0] + self.window_seconds - current))
                return False, retry
            events.append(current)
            return True, 0

    def tracked_keys(self) -> int:
        """Number of source keys currently held. Exposed for tests."""

        with self._lock:
            return len(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._next_sweep = 0.0
