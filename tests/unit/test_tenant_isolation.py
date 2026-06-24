"""Tenant isolation: foreign document id → 404 problem+json (not 403)."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_foreign_document_returns_404(
    api_client_tenant_a: AsyncClient,
    document_id_tenant_b: UUID,
) -> None:
    r = await api_client_tenant_a.get(f"/v1/documents/{document_id_tenant_b}")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.status_code != 403
