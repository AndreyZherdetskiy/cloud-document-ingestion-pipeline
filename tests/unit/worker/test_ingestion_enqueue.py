"""Ingestion worker enqueues exactly one PROCESS_DOCUMENT after MIME-OK path."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from tests.fixtures.worker_session import FakeWorkerSession, event_for

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
from doc_pipeline.worker.events import parse_process_document_message, parse_s3_event_message
from doc_pipeline.worker.ingestion_handlers import handle_ingestion_event


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        aws_region="eu-central-1",
        s3_bucket="dev-doc-pipeline",
        sqs_queue_url="http://localhost/ingest",
        sqs_dlq_url="http://localhost/ingest-dlq",
        sqs_processing_queue_url="http://localhost/processing",
        sqs_processing_dlq_url="http://localhost/processing-dlq",
        jwt_public_key_pem="-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----",
        otel_sdk_disabled=True,
    )


@pytest.mark.asyncio
async def test_ingestion_enqueues_process_document_green() -> None:
    """GREEN: exactly one send_message to processing queue; body is PROCESS_DOCUMENT."""
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    document = Document(
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
    tenant = Tenant(id=tenant_id, name="Acme", slug="acme", config_json={})
    session = FakeWorkerSession(document, tenant)
    settings = _settings()
    sqs = MagicMock()
    sqs.send_message.return_value = {"MessageId": "m-1"}
    body = json.dumps(event_for(document))

    status = await handle_ingestion_event(
        session=session,  # type: ignore[arg-type]
        settings=settings,
        redis=InMemoryRedisCache(),
        sqs_client=sqs,
        body=body,
    )

    assert status is DocumentStatus.QUEUED
    sqs.send_message.assert_called_once()
    call_kwargs = sqs.send_message.call_args.kwargs
    assert call_kwargs["QueueUrl"] == settings.sqs_processing_queue_url
    parsed = parse_process_document_message(call_kwargs["MessageBody"])
    assert parsed.message_type == "PROCESS_DOCUMENT"
    assert parsed.document_id == doc_id
    assert parsed.tenant_id == tenant_id
    assert parsed.s3_bucket == document.s3_bucket
    assert parsed.s3_key == document.s3_key
    # Sanity: ingest envelope still parses (handler used it).
    assert parse_s3_event_message(json.loads(body)).document_id == doc_id


@pytest.mark.asyncio
async def test_ingestion_invalid_mime_sets_failed_no_enqueue() -> None:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    document = Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.UPLOADED.value,
        idempotency_key=f"idem-{doc_id}",
        s3_bucket="dev-doc-pipeline",
        s3_key=f"{tenant_id}/{doc_id}/evil.exe",
        file_name="evil.exe",
        mime_type="application/x-msdownload",
        checksum_sha256="a" * 64,
    )
    tenant = Tenant(id=tenant_id, name="Acme", slug="acme", config_json={})
    session = FakeWorkerSession(document, tenant)
    sqs = MagicMock()

    status = await handle_ingestion_event(
        session=session,  # type: ignore[arg-type]
        settings=_settings(),
        redis=InMemoryRedisCache(),
        sqs_client=sqs,
        body=json.dumps(event_for(document)),
    )

    assert status is DocumentStatus.FAILED
    sqs.send_message.assert_not_called()
    assert "MIME" in (document.failure_reason or "")
