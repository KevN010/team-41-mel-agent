"""Process-wide token bucket for model calls (CLAUDE.md: 60 requests/minute).

Thread safe and asyncio safe. ``acquire`` reserves a token under a lock and then sleeps
outside it, so many threads or tasks queue up in order and none holds the lock while asleep.
Tokens may go negative: that is the queue. ``burst`` is the bucket size. The default is 1, so
calls are spaced ``60/rpm`` seconds apart and no 60 s window ever holds more than ``rpm + 1``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

from mel.settings import settings


class TokenBucket:
    def __init__(
        self,
        rpm: int | None = None,
        *,
        burst: int = 1,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        rpm = settings.RATE_LIMIT_RPM if rpm is None else rpm
        if rpm < 1 or burst < 1:
            raise ValueError("rpm and burst must be >= 1")
        self.rpm = rpm
        self.burst = burst
        self._rate = rpm / 60.0  # tokens per second
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = float(burst)
        self._stamp = monotonic()

    def _reserve(self) -> float:
        """Take one token. Return how many seconds the caller must wait before using it."""
        with self._lock:
            now = self._monotonic()
            self._tokens = min(float(self.burst), self._tokens + (now - self._stamp) * self._rate)
            self._stamp = now
            self._tokens -= 1.0
            if self._tokens >= 0.0:
                return 0.0
            return -self._tokens / self._rate

    def acquire(self) -> float:
        """Block until a token is available. Returns the seconds waited."""
        wait = self._reserve()
        if wait > 0.0:
            self._sleep(wait)
        return wait

    async def acquire_async(self) -> float:
        """Same as acquire, without blocking the event loop."""
        wait = self._reserve()
        if wait > 0.0:
            await asyncio.sleep(wait)
        return wait


_shared: TokenBucket | None = None
_shared_lock = threading.Lock()


def get_bucket() -> TokenBucket:
    """The one bucket for this process. Every model call goes through it."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = TokenBucket(settings.RATE_LIMIT_RPM)
        return _shared


def reset_shared_bucket() -> None:
    """Test helper: drop the shared bucket so the next get_bucket() builds a new one."""
    global _shared
    with _shared_lock:
        _shared = None
