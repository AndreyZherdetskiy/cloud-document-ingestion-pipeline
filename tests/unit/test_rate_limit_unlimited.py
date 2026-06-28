import pytest

from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache


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
