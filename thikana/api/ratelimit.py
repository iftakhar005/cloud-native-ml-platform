"""A per-client rate limit, for a deployment with no firewall or gateway in front of it.

Standard library only, in-process, and deliberately modest:

* It protects the CPU of ONE process from one noisy client. It is not DDoS protection: a
  flood that saturates the host's network is the host's problem, not this module's.
* The state lives in memory, so every replica and every restart has its own counters.
* The client table is BOUNDED. Without that, a caller who rotates source addresses would
  turn the limiter into a memory leak.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping


class RateLimiter:
    """A token bucket per client: `per_minute` tokens refill steadily, up to `burst`."""

    def __init__(self, per_minute: int, burst: int, max_clients: int = 10_000,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if per_minute < 1 or burst < 1 or max_clients < 1:
            raise ValueError("per_minute, burst and max_clients must all be at least 1")
        self.rate = per_minute / 60.0          # tokens per second
        self.burst = float(burst)
        self.max_clients = max_clients
        self._clock = clock
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()   # key -> (tokens, updated)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """Spend one token. Returns (allowed, seconds_until_a_token_is_available)."""
        now = self._clock()
        with self._lock:
            tokens, updated = self._buckets.pop(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - updated) * self.rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self._buckets[key] = (tokens, now)             # most recently used goes last
            while len(self._buckets) > self.max_clients:    # evict the least recently used
                self._buckets.popitem(last=False)
            return allowed, 0.0 if allowed else (1.0 - tokens) / self.rate

    def __len__(self) -> int:
        return len(self._buckets)


def client_key(headers: Mapping[str, str], peer: str | None, trusted_hops: int) -> str:
    """Which address to rate-limit.

    X-Forwarded-For is a list that each proxy APPENDS to, and anything to the LEFT of the
    entries your own proxies added was written by the client, so it can be forged. With
    `trusted_hops` = N proxies in front of the service, the one entry that can be believed
    is the Nth from the right. With 0 (the default) the header is ignored and the socket
    peer is used: behind a proxy that means every client shares one bucket, which is
    annoying but not exploitable, so it is the safe way to be wrong.
    """
    if trusted_hops > 0:
        parts = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops]
    return peer or "unknown"
