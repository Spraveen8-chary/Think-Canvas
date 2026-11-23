"""A small in-memory sliding-window rate limiter.

Used for two things: slowing password guessing, and capping AI calls per user so a bug (or a
user) cannot burn through the API budget. It lives in process memory, which is right for one
server. With several servers you would move the counters to a shared store such as Redis.
"""
import time
from collections import defaultdict, deque

from .errors import RateLimited


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, label: str = "requests"):
        self.limit, self.window_s, self.label = limit, window_s, label
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            wait = max(1, int(self.window_s - (now - hits[0])) + 1)
            raise RateLimited(f"Too many {self.label}. Try again in {wait} seconds.", headers={"Retry-After": str(wait)})
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()
