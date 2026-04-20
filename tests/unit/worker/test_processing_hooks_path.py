"""Processing worker: hooks → PROCESSED/FAILED; duplicate PROCESS_DOCUMENT → hooks once."""

from __future__ import annotations

import pytest
from tests.fixtures.worker_session import FakeWorkerSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.hooks.types import ExtractResult, HookContext, OcrResult
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
from doc_pipeline.worker.events import ProcessDocumentMessage, serialize_process_document_message
from doc_pipeline.worker.processing_handlers import handle_processing_message


def _process_body(document: Document) -> str:
    msg = ProcessDocumentMessage(
        schema_version="1",
        message_type="PROCESS_DOCUMENT",
        job_id=generate_uuidv7(),
        document_id=document.id,
        tenant_id=document.tenant_id,
        document_type=DocumentType(document.document_type),
        s3_bucket=document.s3_bucket or "dev-doc-pipeline",
        s3_key=document.s3_key or "k",
        attempt=1,
        correlation_id=generate_uuidv7(),
        requested_hooks=("virus", "ocr", "extract"),
    )
    return serialize_process_document_message(msg)


@pytest.fixture
def queued_document() -> Document:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    return Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.QUEUED.value,
        idempotency_key=f"idem-{doc_id}",
        s3_bucket="dev-doc-pipeline",
        s3_key=f"{tenant_id}/{doc_id}/invoice.pdf",
        file_name="invoice.pdf",
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(otel_sdk_disabled=True)


@pytest.fixture
def tenant_for(queued_document: Document) -> Tenant:
    return Tenant(id=queued_document.tenant_id, name="Acme", slug="acme", config_json={})


@pytest.fixture
def db_session(queued_document: Document, tenant_for: Tenant) -> FakeWorkerSession:
    return FakeWorkerSession(queued_document, tenant_for)


@pytest.fixture
def redis() -> InMemoryRedisCache:
    return InMemoryRedisCache()


@pytest.mark.asyncio
async def test_processing_happy_path_processed(
    db_session: FakeWorkerSession,
    queued_document: Document,
    settings: Settings,
    redis: InMemoryRedisCache,
) -> None:
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    status = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=_process_body(queued_document),
    )
    assert status is DocumentStatus.PROCESSED
    assert queued_document.status == DocumentStatus.PROCESSED.value
    assert queued_document.processing_result_json is not None
    assert db_session.commits >= 1


@pytest.mark.asyncio
async def test_processing_virus_fail_sets_failed(
    db_session: FakeWorkerSession,
    queued_document: Document,
    settings: Settings,
    redis: InMemoryRedisCache,
) -> None:
    hooks = (StubVirusScanHook(clean=False), StubOcrHook(), StubExtractHook())
    status = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=_process_body(queued_document),
    )
    assert status is DocumentStatus.FAILED
    assert queued_document.status == DocumentStatus.FAILED.value
    assert queued_document.failure_reason is not None


@pytest.mark.asyncio
async def test_duplicate_process_document_runs_hooks_once(
    db_session: FakeWorkerSession,
    queued_document: Document,
    settings: Settings,
    redis: InMemoryRedisCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    calls = {"n": 0}
    real_scan = hooks[0].scan

    async def counting_scan(ctx: object) -> object:
        calls["n"] += 1
        return await real_scan(ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(hooks[0], "scan", counting_scan)
    body = _process_body(queued_document)
    s1 = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=body,
    )
    s2 = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=body,
    )
    assert s1 is DocumentStatus.PROCESSED
    assert s2 is DocumentStatus.PROCESSED  # idempotent: already terminal
    assert calls["n"] == 1


class RaisingExtractHook:
    async def run(self, ctx: HookContext, ocr: OcrResult) -> ExtractResult:
        del ctx, ocr
        raise RuntimeError("extract provider unavailable")


@pytest.mark.asyncio
async def test_processing_hook_raise_sets_failed(
    db_session: FakeWorkerSession,
    queued_document: Document,
    settings: Settings,
    redis: InMemoryRedisCache,
) -> None:
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), RaisingExtractHook())
    status = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,  # type: ignore[arg-type]
        body=_process_body(queued_document),
    )
    assert status is DocumentStatus.FAILED
    assert queued_document.status == DocumentStatus.FAILED.value
    assert "extract" in (queued_document.failure_reason or "").lower()
