"""Async SQLAlchemy session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from doc_pipeline.config.settings import Settings


def get_async_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Build async sessionmaker with expire_on_commit=False (no implicit lazy loads)."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
