"""Ingestion worker: S3 event → MIME validate → QUEUED + PROCESS_DOCUMENT enqueue."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType, JobStatus, JobType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.job import Job
from doc_pipeline.domain.services.idempotency import RedisSetNx, acquire_ingest_lock
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
from doc_pipeline.worker.events import (
    ProcessDocumentMessage,
    parse_s3_event_message,
    serialize_process_document_message,
)
from doc_pipeline.worker.handlers import (
    _TERMINAL_STATUSES,
    _apply_status,
    _load_document,
    _load_tenant,
    _mime_allowed,
    _record_documents_processed,
    _tenant_slug_for_metrics,
)

_INGEST_DONE = frozenset(
    {
        DocumentStatus.QUEUED,
        DocumentStatus.SCANNING,
        DocumentStatus.EXTRACTING,
        *_TERMINAL_STATUSES,
    }
)


async def handle_ingestion_event(
    *,
    session: AsyncSession,
    settings: Settings,
    redis: RedisSetNx | None,
    sqs_client: Any,
    body: str,
    hooks_unused: object | None = None,
) -> DocumentStatus:
    """MIME/validate → QUEUED + send PROCESS_DOCUMENT; terminal MIME fail → FAILED."""
    del hooks_unused
    cache: RedisSetNx = redis if redis is not None else InMemoryRedisCache()
    parsed = parse_s3_event_message(body)

    doc = await _load_document(
        session,
        document_id=parsed.document_id,
        tenant_id=parsed.tenant_id,
    )
    tenant = await _load_tenant(session, parsed.tenant_id)
    tenant_slug = _tenant_slug_for_metrics(tenant)
    correlation_id = parsed.correlation_id or generate_uuidv7()
    document_type = DocumentType(doc.document_type)
    current = DocumentStatus(doc.status)

    if current in _TERMINAL_STATUSES:
        return current

    # Already past ingest — ACK without double-enqueue (at-least-once ingest).
    if current in (DocumentStatus.QUEUED, DocumentStatus.SCANNING, DocumentStatus.EXTRACTING):
        return DocumentStatus.QUEUED

    locked = await acquire_ingest_lock(cache, doc.id)
    if not locked:
        return DocumentStatus(doc.status)

    if current is DocumentStatus.UPLOADING:
        await _apply_status(
            session,
            doc,
            to_status=DocumentStatus.UPLOADED,
            correlation_id=correlation_id,
            payload={"source": "s3_event"},
        )
        current = DocumentStatus.UPLOADED

    if current is DocumentStatus.UPLOADED:
        if not _mime_allowed(doc, tenant):
            await _apply_status(
                session,
                doc,
                to_status=DocumentStatus.FAILED,
                correlation_id=correlation_id,
                failure_reason=f"MIME type {doc.mime_type!r} is not allowed",
                payload={"reason": "invalid_mime"},
            )
            _record_documents_processed(
                status=DocumentStatus.FAILED.value,
                document_type=document_type.value,
                tenant_slug=tenant_slug,
            )
            return DocumentStatus.FAILED

        job_id = generate_uuidv7()
        session.add(
            Job(
                id=job_id,
                document_id=doc.id,
                job_type=JobType.PROCESSING.value,
                status=JobStatus.PENDING.value,
                attempt=1,
            )
        )
        await _apply_status(
            session,
            doc,
            to_status=DocumentStatus.QUEUED,
            correlation_id=correlation_id,
        )

        msg = ProcessDocumentMessage(
            schema_version="1",
            message_type="PROCESS_DOCUMENT",
            job_id=job_id,
            document_id=doc.id,
            tenant_id=doc.tenant_id,
            document_type=document_type,
            s3_bucket=parsed.bucket or (doc.s3_bucket or ""),
            s3_key=parsed.object_key or (doc.s3_key or ""),
            attempt=1,
            correlation_id=correlation_id,
            requested_hooks=("virus", "ocr", "extract"),
        )
        sqs_client.send_message(
            QueueUrl=settings.sqs_processing_queue_url,
            MessageBody=serialize_process_document_message(msg),
        )
        return DocumentStatus.QUEUED

    if current in _INGEST_DONE:
        return DocumentStatus.QUEUED if current not in _TERMINAL_STATUSES else current

    return DocumentStatus(doc.status)
