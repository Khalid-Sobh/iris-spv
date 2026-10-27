"""Tiny rate limiter: at most N calls per hour (the portal allows 60)."""
import time
from collections import deque


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    def __init__(self, max_per_hour: int, clock=time.monotonic):
        self.max = max_per_hour
        self.clock = clock          # injectable so tests need no real waiting
        self.calls: deque[float] = deque()

    def acquire(self) -> None:
        """Call before every request. Raises instead of sleeping: fail loudly."""
        now = self.clock()
        while self.calls and now - self.calls[0] >= 3600:
            self.calls.popleft()    # forget calls older than one hour
        if len(self.calls) >= self.max:
            raise RateLimitExceeded(f"limit of {self.max} requests/hour reached")
        self.calls.append(now)
