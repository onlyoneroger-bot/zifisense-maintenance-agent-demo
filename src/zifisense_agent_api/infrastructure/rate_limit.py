from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client_id: str, bucket: str, limit: int, window_seconds: int = 60) -> bool:
        now = self._clock()
        cutoff = now - window_seconds
        key = (client_id, bucket)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
