"""Async SQLAlchemy session factory."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from doc_pipeline.config.settings import Settings

_LOOP_CACHE_ATTR = "_doc_pipeline_sessionmakers"
_sync_sessionmakers: dict[tuple[str, int, int], async_sessionmaker[AsyncSession]] = {}


def _build_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def get_async_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """One engine per event loop and pool key in this process.

    Store the cache on the running loop so a later ``asyncio.run()`` cannot
    reuse asyncpg connections from a closed loop.
    """
    key = (
        settings.database_url,
        settings.database_pool_size,
        settings.database_max_overflow,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        cached = _sync_sessionmakers.get(key)
        if cached is not None:
            return cached
        maker = _build_sessionmaker(settings)
        _sync_sessionmakers[key] = maker
        return maker

    cache: dict[tuple[str, int, int], async_sessionmaker[AsyncSession]]
    existing = getattr(loop, _LOOP_CACHE_ATTR, None)
    if existing is None:
        cache = {}
        setattr(loop, _LOOP_CACHE_ATTR, cache)
    else:
        cache = existing
    cached = cache.get(key)
    if cached is not None:
        return cached
    maker = _build_sessionmaker(settings)
    cache[key] = maker
    return maker


def clear_sessionmaker_cache() -> None:
    """Drop process-local makers. Also clears the cache on the running loop if any."""
    _sync_sessionmakers.clear()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    cache = getattr(loop, _LOOP_CACHE_ATTR, None)
    if cache is not None:
        cache.clear()
