from __future__ import annotations

import time


class TokenBucket:
    """Sliding window. At most `rate_per_sec` calls in any one-second span."""

    def __init__(self, rate_per_sec: float = 8.0, capacity: float = 8.0) -> None:
        if rate_per_sec <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        if rate_per_sec > 10 or capacity > 10:
            raise ValueError("Public.com allows 10 requests per second")
        self.rate_per_sec = int(rate_per_sec)
        self.capacity = int(capacity)
        self._stamps: list[float] = []

    def acquire(self, now: float | None = None) -> float:
        clock = time.monotonic() if now is None else now
        if self._stamps:
            clock = max(clock, self._stamps[-1])
        limit = min(self.capacity, self.rate_per_sec)
        while True:
            recent = [stamp for stamp in self._stamps if clock - stamp <= 1.0]
            if len(recent) < limit:
                self._stamps.append(clock)
                return clock
            clock = recent[0] + 1.0 + 1e-9
