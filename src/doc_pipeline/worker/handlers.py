"""Shared ingest/processing status helpers (Stage 1 monolithic + Stage 2 split)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from opentelemetry import metrics
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import ActorType, DocumentStatus, DocumentType
from doc_pipeline.domain.errors import InvalidTransitionError, NotFoundError
from doc_pipeline.domain.hooks.base import ExtractHook, OcrHook, VirusScanHook
from doc_pipeline.domain.hooks.types import HookContext
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.audit_log import AuditLog
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.domain.services.idempotency import RedisSetNx, acquire_processing_lock
from doc_pipeline.domain.services.upload_service import (
    DEFAULT_ALLOWED_MIME_TYPES,
    allowed_mime_types_for_tenant,
)
from doc_pipeline.domain.state_machine import transition
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
from doc_pipeline.observability.otel import assert_low_cardinality_attrs
from doc_pipeline.worker.events import S3IngestEvent, parse_s3_event_message

_TERMINAL_STATUSES = frozenset(
    {
        DocumentStatus.PROCESSED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    }
)

_POST_INGEST_STATUSES = frozenset(
    {
        DocumentStatus.QUEUED,
        DocumentStatus.SCANNING,
        DocumentStatus.EXTRACTING,
    }
)


class IngestHooks(Protocol):
    @property
    def virus(self) -> VirusScanHook: ...

    @property
    def ocr(self) -> OcrHook: ...

    @property
    def extract(self) -> ExtractHook: ...


def _hooks_from_tuple(
    hooks: tuple[VirusScanHook, OcrHook, ExtractHook] | IngestHooks,
) -> tuple[VirusScanHook, OcrHook, ExtractHook]:
    if isinstance(hooks, tuple):
        return hooks
    return hooks.virus, hooks.ocr, hooks.extract


def _tenant_slug_for_metrics(tenant: Tenant | None) -> str:
    return tenant.slug if tenant is not None else "unknown"


def _record_documents_processed(
    *,
    status: str,
    document_type: str,
    tenant_slug: str,
) -> None:
    try:
        meter = metrics.get_meter("doc_pipeline.worker")
        counter = meter.create_counter("documents_processed")
        attrs = assert_low_cardinality_attrs(
            {
                "status": status,
                "document_type": document_type,
                "tenant_slug": tenant_slug,
            },
        )
        counter.add(1, attrs)
    except Exception:
        return


def _record_hook_duration(*, hook: str, duration_ms: float) -> None:
    try:
        meter = metrics.get_meter("doc_pipeline.worker")
        hist = meter.create_histogram("hook_duration", unit="ms")
        attrs = assert_low_cardinality_attrs({"hook": hook})
        hist.record(duration_ms, attrs)
    except Exception:
        return


async def _load_document(
    session: AsyncSession,
    *,
    document_id: UUID,
    tenant_id: UUID,
) -> Document:
    row = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
    )
    if row is None:
        raise NotFoundError("Document not found for ingest event")
    return row


async def _load_tenant(session: AsyncSession, tenant_id: UUID) -> Tenant | None:
    row = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    return row if isinstance(row, Tenant) else None


async def _apply_status(
    session: AsyncSession,
    doc: Document,
    *,
    to_status: DocumentStatus,
    correlation_id: UUID,
    failure_reason: str | None = None,
    processing_result: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    from_status = DocumentStatus(doc.status)
    transition(from_status, to_status)
    doc.status = to_status.value
    if failure_reason is not None:
        doc.failure_reason = failure_reason
    if processing_result is not None:
        doc.processing_result_json = processing_result
    if to_status is DocumentStatus.PROCESSED:
        doc.processed_at = datetime.now(UTC)
    session.add(
        AuditLog(
            id=generate_uuidv7(),
            tenant_id=doc.tenant_id,
            document_id=doc.id,
            event_type=f"status.{to_status.value.lower()}",
            from_status=from_status.value,
            to_status=to_status.value,
            actor_type=ActorType.SYSTEM.value,
            actor_id="doc-pipeline-worker",
            payload_json=payload or {},
            correlation_id=correlation_id,
        )
    )
    # Status + audit row in the same transaction (ADR-003).
    await session.commit()


def _mime_allowed(doc: Document, tenant: Tenant | None) -> bool:
    mime = doc.mime_type
    if mime is None:
        return False
    if tenant is None:
        return mime in DEFAULT_ALLOWED_MIME_TYPES
    return mime in allowed_mime_types_for_tenant(tenant.config_json)


async def run_processing_pipeline(
    session: AsyncSession,
    doc: Document,
    *,
    virus: VirusScanHook,
    ocr: OcrHook,
    extract: ExtractHook,
    correlation_id: UUID,
    bucket: str,
    key: str,
    tenant_slug: str,
) -> DocumentStatus:
    """QUEUED → SCANNING → EXTRACTING → PROCESSED|FAILED (hooks + per-step audit)."""
    document_type = DocumentType(doc.document_type)
    current = DocumentStatus(doc.status)

    if current is DocumentStatus.QUEUED:
        await _apply_status(
            session,
            doc,
            to_status=DocumentStatus.SCANNING,
            correlation_id=correlation_id,
        )
        current = DocumentStatus.SCANNING

    ctx = HookContext(
        tenant_id=doc.tenant_id,
        document_id=doc.id,
        document_type=document_type,
        bucket=bucket,
        key=key,
        mime_type=doc.mime_type,
        checksum_sha256=doc.checksum_sha256,
    )

    if current is DocumentStatus.SCANNING:
        try:
            started = time.perf_counter()
            scan = await virus.scan(ctx)
            _record_hook_duration(hook="virus", duration_ms=(time.perf_counter() - started) * 1000)
        except (NotFoundError, InvalidTransitionError):
            raise
        except Exception as exc:
            await _apply_status(
                session,
                doc,
                to_status=DocumentStatus.FAILED,
                correlation_id=correlation_id,
                failure_reason=f"Virus scan hook error: {exc!s}",
                payload={"hook": "virus", "error": str(exc)},
            )
            _record_documents_processed(
                status=DocumentStatus.FAILED.value,
                document_type=document_type.value,
                tenant_slug=tenant_slug,
            )
            return DocumentStatus.FAILED
        if not scan.clean:
            await _apply_status(
                session,
                doc,
                to_status=DocumentStatus.FAILED,
                correlation_id=correlation_id,
                failure_reason=(
                    f"Virus scan failed (scanner={scan.scanner}, scan_id={scan.scan_id})"
                ),
                payload={
                    "scanner": scan.scanner,
                    "scan_id": scan.scan_id,
                    "clean": False,
                },
            )
            _record_documents_processed(
                status=DocumentStatus.FAILED.value,
                document_type=document_type.value,
                tenant_slug=tenant_slug,
            )
            return DocumentStatus.FAILED
        await _apply_status(
            session,
            doc,
            to_status=DocumentStatus.EXTRACTING,
            correlation_id=correlation_id,
            payload={"scanner": scan.scanner, "scan_id": scan.scan_id, "clean": True},
        )
        current = DocumentStatus.EXTRACTING

    if current is DocumentStatus.EXTRACTING:
        try:
            started = time.perf_counter()
            ocr_result = await ocr.run(ctx)
            _record_hook_duration(hook="ocr", duration_ms=(time.perf_counter() - started) * 1000)
        except (NotFoundError, InvalidTransitionError):
            raise
        except Exception as exc:
            await _apply_status(
                session,
                doc,
                to_status=DocumentStatus.FAILED,
                correlation_id=correlation_id,
                failure_reason=f"OCR hook error: {exc!s}",
                payload={"hook": "ocr", "error": str(exc)},
            )
            _record_documents_processed(
                status=DocumentStatus.FAILED.value,
                document_type=document_type.value,
                tenant_slug=tenant_slug,
            )
            return DocumentStatus.FAILED
        try:
            started = time.perf_counter()
            extract_result = await extract.run(ctx, ocr_result)
            _record_hook_duration(
                hook="extract",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except (NotFoundError, InvalidTransitionError):
            raise
        except Exception as exc:
            await _apply_status(
                session,
                doc,
                to_status=DocumentStatus.FAILED,
                correlation_id=correlation_id,
                failure_reason=f"Extract hook error: {exc!s}",
                payload={"hook": "extract", "error": str(exc)},
            )
            _record_documents_processed(
                status=DocumentStatus.FAILED.value,
                document_type=document_type.value,
                tenant_slug=tenant_slug,
            )
            return DocumentStatus.FAILED
        result_payload: dict[str, object] = {
            "ocr": {
                "provider": ocr_result.provider,
                "pages": ocr_result.pages,
                "text_preview": ocr_result.text_preview,
                "confidence": ocr_result.confidence,
            },
            "extract": {
                "document_type": extract_result.document_type.value,
                "payload": extract_result.payload,
            },
        }
        await _apply_status(
            session,
            doc,
            to_status=DocumentStatus.PROCESSED,
            correlation_id=correlation_id,
            processing_result=result_payload,
            payload={"hooks": ["virus", "ocr", "extract"]},
        )
        _record_documents_processed(
            status=DocumentStatus.PROCESSED.value,
            document_type=document_type.value,
            tenant_slug=tenant_slug,
        )
        return DocumentStatus.PROCESSED

    if current in _TERMINAL_STATUSES:
        return current

    return DocumentStatus(doc.status)


async def handle_ingest_event(
    session: AsyncSession,
    hooks: tuple[VirusScanHook, OcrHook, ExtractHook] | IngestHooks,
    event: S3IngestEvent | dict[str, Any] | str,
    settings: Settings,
    *,
    redis: RedisSetNx | None = None,
) -> DocumentStatus:
    """Stage 1 monolithic path: UPLOADED→…→PROCESSED/FAILED (kept for unit/compat)."""
    del settings  # stub toggles / future worker knobs
    cache: RedisSetNx = redis if redis is not None else InMemoryRedisCache()
    parsed = event if isinstance(event, S3IngestEvent) else parse_s3_event_message(event)
    virus, ocr, extract = _hooks_from_tuple(hooks)

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
    # Duplicate delivery after terminal: ACK without re-running hooks (ADR-002).
    if current in _TERMINAL_STATUSES:
        return current

    locked = await acquire_processing_lock(cache, doc.id)
    if not locked:
        # Another worker holds the lock — leave message for visibility retry.
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
        await _apply_status(
            session,
            doc,
            to_status=DocumentStatus.QUEUED,
            correlation_id=correlation_id,
        )
        current = DocumentStatus.QUEUED

    if current in _POST_INGEST_STATUSES:
        return await run_processing_pipeline(
            session,
            doc,
            virus=virus,
            ocr=ocr,
            extract=extract,
            correlation_id=correlation_id,
            bucket=parsed.bucket or (doc.s3_bucket or ""),
            key=parsed.object_key or (doc.s3_key or ""),
            tenant_slug=tenant_slug,
        )

    if current in _TERMINAL_STATUSES:
        return current

    return DocumentStatus(doc.status)
