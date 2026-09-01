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

    def consume(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        """Consume one request and return ``(allowed, retry_after_seconds)``."""

        if self.limit == 0:
            return True, 0
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry = max(1, math.ceil(events[0] + self.window_seconds - current))
                return False, retry
            events.append(current)
            if not events:
                self._events.pop(key, None)
            return True, 0

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
