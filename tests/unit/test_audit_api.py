"""Audit API — document_id required, tenant scoped."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from tests.conftest import TENANT_A, TENANT_B
from tests.fixtures.jwt_keys import mint_token

from doc_pipeline.domain.enums import ActorType, DocumentStatus, DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.services.audit_service import AuditRecord, InMemoryAuditService
from doc_pipeline.domain.services.document_service import DocumentRecord, InMemoryDocumentService


@pytest.fixture
async def operator_client(app) -> AsyncIterator[AsyncClient]:
    token = mint_token(tenant_id=str(TENANT_A), roles=["ROLE_OPERATOR"])
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_audit_requires_document_id(operator_client: AsyncClient) -> None:
    r = await operator_client.get("/v1/audit")
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_audit_foreign_tenant_returns_404(
    operator_client: AsyncClient,
    memory_store: InMemoryDocumentService,
    audit_service: InMemoryAuditService,
) -> None:
    foreign_doc = generate_uuidv7()
    memory_store.seed(
        DocumentRecord(
            id=foreign_doc,
            tenant_id=TENANT_B,
            document_type=DocumentType.INVOICE,
            status=DocumentStatus.DRAFT,
            external_ref=None,
            idempotency_key="audit-foreign",
            title=None,
            metadata={},
            file_name="b.pdf",
            mime_type="application/pdf",
            checksum_sha256="b" * 64,
            file_size_bytes=None,
            created_by="seed",
            correlation_id=generate_uuidv7(),
        )
    )
    audit_service.seed(
        AuditRecord(
            id=generate_uuidv7(),
            tenant_id=TENANT_B,
            document_id=foreign_doc,
            job_id=None,
            event_type="DOCUMENT_CREATED",
            from_status=None,
            to_status="DRAFT",
            actor_type=ActorType.USER,
            actor_id="seed",
            correlation_id=generate_uuidv7(),
        )
    )
    r = await operator_client.get("/v1/audit", params={"document_id": str(foreign_doc)})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_audit_list_for_own_document(
    operator_client: AsyncClient,
    memory_store: InMemoryDocumentService,
    audit_service: InMemoryAuditService,
) -> None:
    doc_id = generate_uuidv7()
    memory_store.seed(
        DocumentRecord(
            id=doc_id,
            tenant_id=TENANT_A,
            document_type=DocumentType.INVOICE,
            status=DocumentStatus.DRAFT,
            external_ref=None,
            idempotency_key="audit-own",
            title=None,
            metadata={},
            file_name="a.pdf",
            mime_type="application/pdf",
            checksum_sha256="a" * 64,
            file_size_bytes=None,
            created_by="seed",
            correlation_id=generate_uuidv7(),
        )
    )
    event_id = generate_uuidv7()
    audit_service.seed(
        AuditRecord(
            id=event_id,
            tenant_id=TENANT_A,
            document_id=doc_id,
            job_id=None,
            event_type="DOCUMENT_CREATED",
            from_status=None,
            to_status="DRAFT",
            actor_type=ActorType.USER,
            actor_id="seed",
            correlation_id=generate_uuidv7(),
        )
    )
    r = await operator_client.get("/v1/audit", params={"document_id": str(doc_id)})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(event_id)
    assert items[0]["event_type"] == "DOCUMENT_CREATED"
