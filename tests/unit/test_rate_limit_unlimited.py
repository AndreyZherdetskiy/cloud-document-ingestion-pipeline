from unittest.mock import MagicMock

import pytest

from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache, RedisRateLimitClient


@pytest.mark.asyncio
async def test_limit_zero_allows_every_request() -> None:
    cache = InMemoryRedisCache()
    for _ in range(50):
        assert await cache.check_rate_limit("rl:t", limit=0) is True


@pytest.mark.asyncio
async def test_positive_limit_still_exhausts() -> None:
    cache = InMemoryRedisCache()
    assert await cache.check_rate_limit("rl:t", limit=2) is True
    assert await cache.check_rate_limit("rl:t", limit=2) is True
    assert await cache.check_rate_limit("rl:t", limit=2) is False


@pytest.mark.asyncio
async def test_redis_rate_limit_client_unlimited_skips_pipeline() -> None:
    client = RedisRateLimitClient.__new__(RedisRateLimitClient)
    inner = MagicMock()
    client._client = inner
    allowed = await client.check_rate_limit("rl:t", limit=0)
    assert allowed is True
    inner.pipeline.assert_not_called()
