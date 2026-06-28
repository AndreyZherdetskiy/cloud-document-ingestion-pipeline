import asyncio
from unittest.mock import MagicMock, patch

import pytest

from doc_pipeline.config.settings import Settings, get_settings
from doc_pipeline.infrastructure.db.session import (
    clear_sessionmaker_cache,
    get_async_sessionmaker,
)


def test_pool_defaults_match_sqlalchemy() -> None:
    s = Settings(DATABASE_URL="postgresql+asyncpg://t:t@localhost:5432/t")
    assert s.database_pool_size == 5
    assert s.database_max_overflow == 10


def test_pool_env_override(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_POOL_SIZE", "2")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "1")
    get_settings.cache_clear()
    s = Settings()
    assert s.database_pool_size == 2
    assert s.database_max_overflow == 1
    get_settings.cache_clear()


def test_sessionmaker_passes_pool_kwargs() -> None:
    clear_sessionmaker_cache()
    captured: dict[str, object] = {}

    def _spy(url: str, **kwargs: object) -> object:
        captured.update(kwargs)
        captured["url"] = url
        engine = MagicMock(name="engine")
        return engine

    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:1/none",
        DATABASE_POOL_SIZE=2,
        DATABASE_MAX_OVERFLOW=1,
    )
    with patch("doc_pipeline.infrastructure.db.session.create_async_engine", side_effect=_spy):
        get_async_sessionmaker(settings)
        get_async_sessionmaker(settings)
    assert captured["pool_size"] == 2
    assert captured["max_overflow"] == 1
    assert captured["pool_pre_ping"] is True
    clear_sessionmaker_cache()


def test_sessionmaker_is_cached_per_pool_key() -> None:
    clear_sessionmaker_cache()
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:1/none",
        DATABASE_POOL_SIZE=3,
        DATABASE_MAX_OVERFLOW=2,
    )
    first = get_async_sessionmaker(settings)
    second = get_async_sessionmaker(settings)
    assert first is second
    clear_sessionmaker_cache()


@pytest.mark.asyncio
async def test_sessionmaker_is_cached_on_running_loop() -> None:
    clear_sessionmaker_cache()
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:1/none",
        DATABASE_POOL_SIZE=4,
        DATABASE_MAX_OVERFLOW=2,
    )
    first = get_async_sessionmaker(settings)
    second = get_async_sessionmaker(settings)
    assert first is second
    clear_sessionmaker_cache()
    third = get_async_sessionmaker(settings)
    assert third is not first
    clear_sessionmaker_cache()


def test_sessionmaker_is_not_reused_across_asyncio_run() -> None:
    clear_sessionmaker_cache()
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:1/none",
        DATABASE_POOL_SIZE=4,
        DATABASE_MAX_OVERFLOW=1,
    )

    async def _one() -> object:
        return get_async_sessionmaker(settings)

    first = asyncio.run(_one())
    second = asyncio.run(_one())
    assert first is not second
    clear_sessionmaker_cache()
