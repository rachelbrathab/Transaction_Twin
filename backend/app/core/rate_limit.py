"""Rate limiter for authentication endpoints.

Provides per-IP rate limiting for login and signup to prevent brute-force
attacks and account spam.

Two backends:
  - Redis-backed: used in production (multi-process safe)
  - In-memory: used in development/test (single-process)

If Redis is unavailable at runtime, the limiter falls back to in-memory.
"""

from __future__ import annotations

import time
from collections import defaultdict

import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger()


# ── In-Memory Backend ──────────────────────────────────────────────


class InMemoryRateLimiter:
    """Sliding window rate limiter using in-memory storage.

    Thread-safe for single-process deployments.
    Not suitable for multi-process/multi-instance deployments.
    """

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
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


# ── Redis Backend ──────────────────────────────────────────────────


class RedisRateLimiter:
    """Sliding window rate limiter backed by Redis.

    Uses sorted sets for atomic sliding window counting.
    Safe for multi-process/multi-instance deployments.
    Falls back to in-memory if Redis is unavailable.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis = None
        self._connected = False
        self._fallback = InMemoryRateLimiter()

    async def _get_redis(self):  # noqa: ANN202
        if self._connected and self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            await self._redis.ping()
            self._connected = True
            logger.info("rate_limiter_redis_connected")
            return self._redis
        except Exception:
            self._connected = False
            logger.warning("rate_limiter_redis_unavailable_fallback_in_memory")
            return None

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        """Check if a request is allowed using Redis sliding window.

        Falls back to in-memory if Redis is unavailable.
        """
        redis_client = await self._get_redis()
        if redis_client is None:
            # Fallback to in-memory
            await self._fallback.check(key, limit, window_seconds)
            return

        try:
            now = time.time()
            window_key = f"ratelimit:{key}"
            cutoff = now - window_seconds

            pipe = redis_client.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(window_key, 0, cutoff)
            # Count current entries
            pipe.zcard(window_key)
            # Add current request
            pipe.zadd(window_key, {str(now): now})
            # Set TTL
            pipe.expire(window_key, window_seconds + 1)
            results = await pipe.execute()

            current_count = results[1]
            if current_count >= limit:
                # Remove the request we just added
                await redis_client.zrem(window_key, str(now))
                retry_after = window_seconds
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception:
            # Redis error — fall back to in-memory
            logger.warning("rate_limiter_redis_error_fallback_in_memory")
            await self._fallback.check(key, limit, window_seconds)


# ── Singleton ──────────────────────────────────────────────────────

# Module-level rate limiter instance.
# Initialized lazily based on configuration.
_rate_limiter = None


def get_rate_limiter():  # noqa: ANN202
    """Get the application rate limiter.

    Uses Redis in production, in-memory in development/test.
    Returns a singleton.
    """
    global _rate_limiter  # noqa: PLW0603
    if _rate_limiter is not None:
        return _rate_limiter

    from app.core.config import get_settings
    settings = get_settings()

    if settings.is_production and settings.redis_url:
        _rate_limiter = RedisRateLimiter(settings.redis_url)
    else:
        _rate_limiter = InMemoryRateLimiter()

    return _rate_limiter


# For backward compatibility
rate_limiter = InMemoryRateLimiter()


def clear_rate_limiter() -> None:
    """Clear rate limiter state — used in tests."""
    global _rate_limiter  # noqa: PLW0603
    if _rate_limiter is not None and isinstance(_rate_limiter, InMemoryRateLimiter):
        _rate_limiter._requests.clear()
    rate_limiter._requests.clear()


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
