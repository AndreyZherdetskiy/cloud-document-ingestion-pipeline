"""Shared pytest fixtures — JWT stub, in-memory store, no live PG for unit tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from tests.fixtures.jwt_keys import PUBLIC_PEM, mint_token

from doc_pipeline.api.deps import (
    get_audit_service,
    get_db_session,
    get_dlq_service,
    get_document_service,
    get_job_service,
    get_redis,
    get_s3_client,
    get_settings_dep,
    get_upload_service,
)
from doc_pipeline.config.settings import Settings, get_settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.services.audit_service import InMemoryAuditService
from doc_pipeline.domain.services.dlq_service import FakeDlqService
from doc_pipeline.domain.services.document_service import (
    DocumentRecord,
    InMemoryDocumentService,
)
from doc_pipeline.domain.services.job_service import InMemoryJobService
from doc_pipeline.domain.services.upload_service import (
    InMemoryTenantConfigService,
    InMemoryUploadService,
)
from doc_pipeline.infrastructure.aws.s3 import get_s3_client as build_s3_client
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
from doc_pipeline.main import create_app

TENANT_A = UUID("01900000-0000-7000-8000-0000000000a1")
TENANT_B = UUID("01900000-0000-7000-8000-0000000000b2")


class _NoOpAsyncSession:
    """Stand-in so HTTP unit tests can call session.commit() without Postgres."""

    async def commit(self) -> None:
        return None


async def _noop_db_session() -> AsyncIterator[_NoOpAsyncSession]:
    yield _NoOpAsyncSession()


@pytest.fixture(autouse=True)
def _isolate_unit_tests_from_local_env(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if request.node.get_closest_marker("integration") or request.node.get_closest_marker("e2e"):
        return
    get_settings.cache_clear()
    monkeypatch.setenv("AWS_ENDPOINT_URL", "")
    monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", "")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", "")


@pytest.fixture
def jwt_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", PUBLIC_PEM)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", "")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", "")
    monkeypatch.setenv("JWT_ISSUER", "http://localhost:8000/dev-issuer")
    monkeypatch.setenv("JWT_AUDIENCE", "doc-pipeline")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "")
    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


@pytest.fixture
def memory_store() -> InMemoryDocumentService:
    return InMemoryDocumentService()


@pytest.fixture
def memory_redis() -> InMemoryRedisCache:
    return InMemoryRedisCache()


@pytest.fixture
def tenant_config_service() -> InMemoryTenantConfigService:
    return InMemoryTenantConfigService()


@pytest.fixture
def upload_service(
    memory_store: InMemoryDocumentService,
    tenant_config_service: InMemoryTenantConfigService,
) -> InMemoryUploadService:
    return InMemoryUploadService(memory_store, tenant_config_service)


@pytest.fixture
def job_service() -> InMemoryJobService:
    return InMemoryJobService()


@pytest.fixture
def audit_service(memory_store: InMemoryDocumentService) -> InMemoryAuditService:
    return InMemoryAuditService(memory_store)


@pytest.fixture
def fake_dlq_service() -> FakeDlqService:
    return FakeDlqService()


@pytest.fixture
def app(
    jwt_settings: Settings,
    memory_store: InMemoryDocumentService,
    memory_redis: InMemoryRedisCache,
    upload_service: InMemoryUploadService,
    job_service: InMemoryJobService,
    audit_service: InMemoryAuditService,
    fake_dlq_service: FakeDlqService,
):
    application = create_app()
    application.dependency_overrides[get_settings_dep] = lambda: jwt_settings
    application.dependency_overrides[get_document_service] = lambda: memory_store
    application.dependency_overrides[get_redis] = lambda: memory_redis
    application.dependency_overrides[get_upload_service] = lambda: upload_service
    application.dependency_overrides[get_s3_client] = lambda: build_s3_client(jwt_settings)
    application.dependency_overrides[get_job_service] = lambda: job_service
    application.dependency_overrides[get_audit_service] = lambda: audit_service
    application.dependency_overrides[get_dlq_service] = lambda: fake_dlq_service
    application.dependency_overrides[get_db_session] = _noop_db_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def api_client_tenant_a(app) -> AsyncIterator[AsyncClient]:
    token = mint_token(tenant_id=str(TENANT_A), roles=["ROLE_API_CLIENT"])
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest.fixture
async def api_client_tenant_b(app) -> AsyncIterator[AsyncClient]:
    token = mint_token(tenant_id=str(TENANT_B), roles=["ROLE_API_CLIENT"])
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest.fixture
def document_id_tenant_b(memory_store: InMemoryDocumentService) -> UUID:
    doc_id = generate_uuidv7()
    memory_store.seed(
        DocumentRecord(
            id=doc_id,
            tenant_id=TENANT_B,
            document_type=DocumentType.INVOICE,
            status=DocumentStatus.DRAFT,
            external_ref="tenant-b-ref",
            idempotency_key="seed-b",
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
    return doc_id


@pytest.fixture
def moto_s3_bucket(jwt_settings: Settings) -> str:
    return jwt_settings.s3_bucket


@pytest.fixture
async def draft_document_id(api_client_tenant_a: AsyncClient) -> UUID:
    body = {
        "document_type": "INVOICE",
        "external_ref": "presign-draft",
        "file_name": "invoice.pdf",
        "content_type": "application/pdf",
        "checksum_sha256": "a" * 64,
    }
    r = await api_client_tenant_a.post(
        "/v1/documents",
        json=body,
        headers={"Idempotency-Key": "idem-presign-draft"},
    )
    assert r.status_code == 201
    return UUID(r.json()["id"])


@pytest.fixture
def fake_redis_rate_limit_exhausted(app, memory_redis: InMemoryRedisCache) -> InMemoryRedisCache:
    memory_redis.force_exhausted = True
    app.dependency_overrides[get_redis] = lambda: memory_redis
    return memory_redis
