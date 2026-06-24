"""Behavioral tests for documents API (idempotency + rate limit)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

CREATE_BODY = {
    "document_type": "INVOICE",
    "external_ref": "inv-001",
    "file_name": "invoice.pdf",
    "content_type": "application/pdf",
    "checksum_sha256": "a" * 64,
}


@pytest.mark.asyncio
async def test_create_document_returns_201_draft(api_client_tenant_a: AsyncClient) -> None:
    r = await api_client_tenant_a.post(
        "/v1/documents",
        json=CREATE_BODY,
        headers={"Idempotency-Key": "idem-create"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "DRAFT"
    assert body["document_type"] == "INVOICE"
    assert "id" in body
    assert isinstance(body["id"], str)
    assert "-" in body["id"]  # UUID, not integer


@pytest.mark.asyncio
async def test_missing_jwt_returns_401(app) -> None:
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/documents",
            json=CREATE_BODY,
            headers={"Idempotency-Key": "idem-noauth"},
        )
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_idempotency_same_key_same_payload_returns_200_same_id(
    api_client_tenant_a: AsyncClient,
) -> None:
    headers = {"Idempotency-Key": "idem-001"}
    r1 = await api_client_tenant_a.post("/v1/documents", json=CREATE_BODY, headers=headers)
    assert r1.status_code == 201
    doc_id = r1.json()["id"]

    r2 = await api_client_tenant_a.post("/v1/documents", json=CREATE_BODY, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_idempotency_same_key_different_payload_returns_409(
    api_client_tenant_a: AsyncClient,
) -> None:
    headers = {"Idempotency-Key": "idem-002"}
    r1 = await api_client_tenant_a.post("/v1/documents", json=CREATE_BODY, headers=headers)
    assert r1.status_code == 201

    conflicting = {**CREATE_BODY, "external_ref": "inv-002"}
    r2 = await api_client_tenant_a.post("/v1/documents", json=conflicting, headers=headers)
    assert r2.status_code == 409
    assert r2.headers["content-type"].startswith("application/problem+json")
    assert r2.json().get("title") or r2.json().get("detail")


@pytest.mark.asyncio
async def test_rate_limit_exhausted_returns_429(
    api_client_tenant_a: AsyncClient,
    fake_redis_rate_limit_exhausted,
) -> None:
    r = await api_client_tenant_a.post(
        "/v1/documents",
        json=CREATE_BODY,
        headers={"Idempotency-Key": "idem-rate-limit"},
    )
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_list_documents_cursor_pagination(api_client_tenant_a: AsyncClient) -> None:
    for i in range(3):
        await api_client_tenant_a.post(
            "/v1/documents",
            json={**CREATE_BODY, "external_ref": f"list-{i}"},
            headers={"Idempotency-Key": f"idem-list-{i}"},
        )
    r = await api_client_tenant_a.get("/v1/documents", params={"limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert "next_cursor" in body
    assert "offset" not in body


@pytest.mark.asyncio
async def test_get_document_ok(api_client_tenant_a: AsyncClient) -> None:
    created = await api_client_tenant_a.post(
        "/v1/documents",
        json=CREATE_BODY,
        headers={"Idempotency-Key": "idem-get"},
    )
    doc_id = created.json()["id"]
    r = await api_client_tenant_a.get(f"/v1/documents/{doc_id}")
    assert r.status_code == 200
    assert r.json()["id"] == doc_id
