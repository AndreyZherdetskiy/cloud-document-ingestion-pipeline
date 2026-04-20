"""Unit test: ready probe fails when PostgreSQL is down (override, no live PG)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.api.deps import get_db_session
from doc_pipeline.main import create_app


class _FailingSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise OSError("connection refused")


@pytest.mark.asyncio
async def test_ready_fails_when_postgres_down() -> None:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield _FailingSession()  # type: ignore[misc]

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/ready")
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
