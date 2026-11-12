"""Server-side replay protection: memory of recently accepted request nonces."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from orbital.bridges.auth.errors import AuthenticationError, AuthFailureReason


class NonceCache:
    """Remembers accepted nonces for ``ttl_seconds`` so that replayed requests are refused.

    The cache is thread-safe and bounded. When it is full even after expired entries are purged,
    new requests are refused rather than weakening replay protection.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        capacity: int = 100_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._expiry: dict[str, float] = {}
        self._lock = threading.Lock()

    def remember(self, nonce: str) -> None:
        """Record *nonce*; raise ``AuthenticationError`` on a replay or when the cache is full."""
        with self._lock:
            now = self._clock()
            # Entries are inserted in time order, so expired ones are at the front.
            while self._expiry:
                oldest = next(iter(self._expiry))
                if self._expiry[oldest] > now:
                    break
                del self._expiry[oldest]
            if nonce in self._expiry:
                raise AuthenticationError(
                    AuthFailureReason.REPLAYED_NONCE, "this request nonce was already used"
                )
            if len(self._expiry) >= self._capacity:
                raise AuthenticationError(
                    AuthFailureReason.NONCE_CACHE_FULL,
                    "too many recent requests to guarantee replay protection; retry later",
                )
            self._expiry[nonce] = now + self._ttl

    def __len__(self) -> int:
        with self._lock:
            return len(self._expiry)
