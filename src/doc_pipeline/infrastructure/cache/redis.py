"""Redis client for rate limiting and short-lived locks (in-memory fake for unit tests)."""

from __future__ import annotations

from typing import Any, Protocol

import redis.asyncio as redis


class RedisCache(Protocol):
    async def check_rate_limit(self, key: str, *, limit: int, window_seconds: int = 60) -> bool:
        """Return True when the request is allowed; False when the bucket is exhausted."""
        ...

    async def set_nx(self, key: str, value: str, *, ex: int | None = None) -> bool: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class InMemoryRedisCache:
    """Process-local Redis stand-in for unit tests (SET NX / counters)."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._nx: dict[str, str] = {}
        self.force_exhausted: bool = False

    async def check_rate_limit(self, key: str, *, limit: int, window_seconds: int = 60) -> bool:
        del window_seconds  # fixed-window ignored in unit fake
        if limit <= 0:
            return True
        if self.force_exhausted:
            return False
        current = self._counts.get(key, 0) + 1
        self._counts[key] = current
        return current <= limit

    async def set_nx(self, key: str, value: str, *, ex: int | None = None) -> bool:
        del ex  # TTL ignored in unit fake; keys live for process lifetime
        if key in self._nx:
            return False
        self._nx[key] = value
        return True

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._counts.clear()
        self._nx.clear()


class RedisRateLimitClient:
    """Thin wrapper around redis.asyncio for rate-limit INCR + EXPIRE."""

    def __init__(self, url: str) -> None:
        self._client: Any = redis.from_url(url, decode_responses=True)

    async def check_rate_limit(self, key: str, *, limit: int, window_seconds: int = 60) -> bool:
        if limit <= 0:
            return True
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = await pipe.execute()
        return int(count) <= limit

    async def set_nx(self, key: str, value: str, *, ex: int | None = None) -> bool:
        return bool(await self._client.set(key, value, nx=True, ex=ex))

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def close(self) -> None:
        await self._client.aclose()
