from sqlalchemy.pool import QueuePool

from doc_pipeline.config.settings import Settings, get_settings
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker


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


def test_sessionmaker_uses_pool_settings() -> None:
    s = Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:1/none",
        DATABASE_POOL_SIZE=2,
        DATABASE_MAX_OVERFLOW=1,
    )
    session_factory = get_async_sessionmaker(s)
    pool = session_factory.kw["bind"].pool
    assert isinstance(pool, QueuePool)
    assert pool._pool.maxsize == 2
    assert pool._max_overflow == 1
