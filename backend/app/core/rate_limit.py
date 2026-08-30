"""Lightweight in-memory rate limiter for authentication endpoints.

Provides per-IP rate limiting for login and signup to prevent brute-force
attacks and account spam. Designed to be replaced with Redis-backed limiter
in production multi-instance deployments.

Current implementation is single-process only. For multi-process deployments,
replace with Redis-backed sliding window counter.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    """Sliding window rate limiter using in-memory storage.

    Tracks request counts per key (typically IP address) within a
    time window. Returns HTTP 429 when the limit is exceeded.

    Thread-safe for single-process deployments.
    Not suitable for multi-process/multi-instance deployments.
    """

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        """Check if a request is allowed.

        Args:
            key: Rate limit key (e.g., IP address).
            limit: Maximum requests allowed in the window.
            window_seconds: Time window in seconds.

        Raises:
            HTTPException: 429 if rate limit exceeded.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        # Remove expired entries
        self._requests[key] = [
            t for t in self._requests[key] if t > cutoff
        ]

        if len(self._requests[key]) >= limit:
            retry_after = int(self._requests[key][0] - cutoff) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

        self._requests[key].append(now)


# Module-level singleton for application-wide use.
# In production, replace with Redis-backed implementation.
rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting proxy headers."""
    # Check X-Forwarded-For first (for reverse proxy setups)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP (nginx convention)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client IP
    if request.client:
        return request.client.host

    return "unknown"
