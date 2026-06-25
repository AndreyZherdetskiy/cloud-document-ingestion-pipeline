"""Admin DLQ replay — Platform Admin only."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from tests.conftest import TENANT_A
from tests.fixtures.jwt_keys import mint_token


@pytest.fixture
async def platform_admin_client(app) -> AsyncIterator[AsyncClient]:
    token = mint_token(tenant_id=str(TENANT_A), roles=["ROLE_PLATFORM_ADMIN"])
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_dlq_replay_forbidden_for_api_client(api_client_tenant_a: AsyncClient) -> None:
    r = await api_client_tenant_a.post(
        "/v1/admin/dlq/replay",
        json={"message_ids": ["abc"]},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_dlq_replay_forbidden_for_operator(app) -> None:
    token = mint_token(tenant_id=str(TENANT_A), roles=["ROLE_OPERATOR"])
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        r = await client.post(
            "/v1/admin/dlq/replay",
            json={"message_ids": ["abc"]},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_dlq_replay_ok_for_platform_admin(
    platform_admin_client: AsyncClient,
    fake_dlq_service,
) -> None:
    r = await platform_admin_client.post(
        "/v1/admin/dlq/replay",
        json={"message_ids": ["msg-1", "msg-2"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["replayed_count"] == 2
    assert set(body["message_ids"]) == {"msg-1", "msg-2"}
    assert fake_dlq_service.replayed == ["msg-1", "msg-2"]
