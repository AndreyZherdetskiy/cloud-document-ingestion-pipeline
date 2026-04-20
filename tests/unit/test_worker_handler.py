"""Unit tests for SQS ingest handler (virus / happy / invalid MIME)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from tests.fixtures.worker_session import FakeWorkerSession, event_for

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.errors import NotFoundError
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.hooks.types import ExtractResult, HookContext, OcrResult
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.audit_log import AuditLog
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.worker.events import parse_s3_event_message
from doc_pipeline.worker.handlers import handle_ingest_event


@pytest.fixture
def settings() -> Settings:
    return Settings(otel_sdk_disabled=True)


@pytest.fixture
def uploaded_document() -> Document:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    return Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.UPLOADED.value,
        idempotency_key=f"idem-{doc_id}",
        s3_bucket="dev-doc-pipeline",
        s3_key=f"{tenant_id}/{doc_id}/invoice.pdf",
        file_name="invoice.pdf",
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
    )


@pytest.fixture
def tenant_for(uploaded_document: Document) -> Tenant:
    return Tenant(
        id=uploaded_document.tenant_id,
        name="Acme",
        slug="acme",
        config_json={},
    )


@pytest.fixture
def db_session(uploaded_document: Document, tenant_for: Tenant) -> FakeWorkerSession:
    return FakeWorkerSession(uploaded_document, tenant_for)


def test_parse_s3_event_from_object_key() -> None:
    tenant_id = generate_uuidv7()
    document_id = generate_uuidv7()
    key = f"{tenant_id}/{document_id}/report.pdf"
    event = parse_s3_event_message(
        {
            "bucket": "dev-doc-pipeline",
            "object_key": key,
            "etag": "etag-1",
        }
    )
    assert event.tenant_id == tenant_id
    assert event.document_id == document_id
    assert event.object_key == key


def test_parse_raw_s3_records() -> None:
    tenant_id = generate_uuidv7()
    document_id = generate_uuidv7()
    body = {
        "Records": [
            {
                "eventSource": "aws:s3",
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "bucket": {"name": "dev-doc-pipeline"},
                    "object": {
                        "key": f"{tenant_id}/{document_id}/f.pdf",
                        "eTag": '"abc"',
                        "size": 12,
                    },
                },
            }
        ]
    }
    event = parse_s3_event_message(body)
    assert event.tenant_id == tenant_id
    assert event.document_id == document_id
    assert event.etag == "abc"


@pytest.mark.asyncio
async def test_virus_fail_sets_failed(
    db_session: FakeWorkerSession,
    uploaded_document: Document,
    settings: Settings,
) -> None:
    hooks = (
        StubVirusScanHook(clean=False),
        StubOcrHook(),
        StubExtractHook(),
    )
    status = await handle_ingest_event(
        db_session,  # type: ignore[arg-type]
        hooks,
        event_for(uploaded_document),
        settings,
    )
    assert status is DocumentStatus.FAILED
    assert uploaded_document.status == DocumentStatus.FAILED.value
    assert uploaded_document.failure_reason is not None
    rows = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.document_id == uploaded_document.id,
                AuditLog.to_status == DocumentStatus.FAILED.value,
            )
        )
    ).all()
    assert len(rows) >= 1
    assert db_session.commits >= 1


@pytest.mark.asyncio
async def test_happy_path_processed(
    db_session: FakeWorkerSession,
    uploaded_document: Document,
    settings: Settings,
) -> None:
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    status = await handle_ingest_event(
        db_session,  # type: ignore[arg-type]
        hooks,
        event_for(uploaded_document),
        settings,
    )
    assert status is DocumentStatus.PROCESSED
    assert uploaded_document.status == DocumentStatus.PROCESSED.value
    assert uploaded_document.processing_result_json is not None
    audit_chain = [o for o in db_session.added if isinstance(o, AuditLog)]
    to_statuses = [a.to_status for a in audit_chain]
    assert DocumentStatus.QUEUED.value in to_statuses
    assert DocumentStatus.SCANNING.value in to_statuses
    assert DocumentStatus.EXTRACTING.value in to_statuses
    assert DocumentStatus.PROCESSED.value in to_statuses
    assert db_session.commits == len(audit_chain)


@pytest.mark.asyncio
async def test_invalid_mime_sets_failed(
    db_session: FakeWorkerSession,
    uploaded_document: Document,
    settings: Settings,
) -> None:
    uploaded_document.mime_type = "application/x-msdownload"
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    status = await handle_ingest_event(
        db_session,  # type: ignore[arg-type]
        hooks,
        event_for(uploaded_document),
        settings,
    )
    assert status is DocumentStatus.FAILED
    assert "MIME" in (uploaded_document.failure_reason or "")
    rows = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.document_id == uploaded_document.id,
                AuditLog.to_status == DocumentStatus.FAILED.value,
            )
        )
    ).all()
    assert len(rows) >= 1
    # Virus hook must not run after MIME failure.
    assert uploaded_document.status == DocumentStatus.FAILED.value


@pytest.mark.asyncio
async def test_uploading_promoted_to_uploaded_then_processed(
    settings: Settings,
) -> None:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    doc = Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.UPLOADING.value,
        idempotency_key=f"idem-{doc_id}",
        s3_bucket="dev-doc-pipeline",
        s3_key=f"{tenant_id}/{doc_id}/invoice.pdf",
        mime_type="application/pdf",
        checksum_sha256="b" * 64,
    )
    tenant = Tenant(id=tenant_id, name="Acme", slug="acme", config_json={})
    session = FakeWorkerSession(doc, tenant)
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    status = await handle_ingest_event(
        session,  # type: ignore[arg-type]
        hooks,
        event_for(doc),
        settings,
    )
    assert status is DocumentStatus.PROCESSED
    statuses = [a.to_status for a in session.added if isinstance(a, AuditLog)]
    assert statuses[0] == DocumentStatus.UPLOADED.value


class RaisingExtractHook:
    """Test double — raises on extract.run (production stubs stay non-raising)."""

    async def run(self, ctx: HookContext, ocr: OcrResult) -> ExtractResult:
        del ctx, ocr
        raise RuntimeError("extract provider unavailable")


@pytest.mark.asyncio
async def test_extract_hook_raise_sets_failed(
    db_session: FakeWorkerSession,
    uploaded_document: Document,
    settings: Settings,
) -> None:
    hooks = (
        StubVirusScanHook(clean=True),
        StubOcrHook(),
        RaisingExtractHook(),
    )
    status = await handle_ingest_event(
        db_session,  # type: ignore[arg-type]
        hooks,
        event_for(uploaded_document),
        settings,
    )
    assert status is DocumentStatus.FAILED
    assert uploaded_document.status == DocumentStatus.FAILED.value
    assert uploaded_document.failure_reason is not None
    assert "extract" in uploaded_document.failure_reason.lower()
    audit_chain = [o for o in db_session.added if isinstance(o, AuditLog)]
    to_statuses = [a.to_status for a in audit_chain]
    assert DocumentStatus.SCANNING.value in to_statuses
    assert DocumentStatus.EXTRACTING.value in to_statuses
    assert DocumentStatus.PROCESSED.value not in to_statuses
    failed_rows = [a for a in audit_chain if a.to_status == DocumentStatus.FAILED.value]
    assert len(failed_rows) == 1
    assert db_session.commits == len(audit_chain)


@pytest.mark.asyncio
async def test_not_found_error_not_swallowed_by_hook_handler(
    uploaded_document: Document,
    settings: Settings,
) -> None:
    session = FakeWorkerSession(uploaded_document, tenant=None)
    session.document = uploaded_document  # type: ignore[misc]

    async def scalar_missing(_stmt: object) -> None:
        return None

    session.scalar = scalar_missing  # type: ignore[method-assign]
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    with pytest.raises(NotFoundError):
        await handle_ingest_event(
            session,  # type: ignore[arg-type]
            hooks,
            event_for(uploaded_document),
            settings,
        )
