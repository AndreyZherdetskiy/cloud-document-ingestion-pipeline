"""Processing worker: PROCESS_DOCUMENT → virus/ocr/extract → PROCESSED|FAILED."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.hooks.base import ExtractHook, OcrHook, VirusScanHook
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.domain.services.idempotency import RedisSetNx, acquire_processing_lock
from doc_pipeline.domain.services.webhook_service import (
    WebhookEventType,
    build_webhook_payload,
    deliver_webhook,
)
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
from doc_pipeline.worker.events import parse_process_document_message
from doc_pipeline.worker.handlers import (
    _TERMINAL_STATUSES,
    _load_document,
    _load_tenant,
    _tenant_slug_for_metrics,
    run_processing_pipeline,
)

logger = structlog.get_logger(__name__)

_TERMINAL_WEBHOOK_EVENTS: dict[DocumentStatus, WebhookEventType] = {
    DocumentStatus.PROCESSED: "document.processed",
    DocumentStatus.FAILED: "document.failed",
}


def _webhook_target(
    tenant: Tenant | None,
    settings: Settings,
) -> tuple[str, str] | None:
    cfg: dict[str, Any] = dict(tenant.config_json) if tenant is not None else {}
    raw_url = cfg.get("webhook_url") or settings.webhook_default_url
    raw_secret = cfg.get("webhook_secret") or settings.webhook_default_secret
    url = str(raw_url).strip() if raw_url else ""
    secret = str(raw_secret) if raw_secret else ""
    if not url or not secret:
        return None
    return url, secret


async def _notify_terminal_webhook(
    *,
    session: AsyncSession,
    settings: Settings,
    doc: Document,
    status: DocumentStatus,
    skip: bool,
) -> None:
    """Fire signed webhook after durable PROCESSED/FAILED; never raises into SQS path."""
    event_type = _TERMINAL_WEBHOOK_EVENTS.get(status)
    if event_type is None:
        return
    try:
        tenant = await _load_tenant(session, doc.tenant_id)
        target = _webhook_target(tenant, settings)
        if target is None:
            return
        url, secret = target
        payload = build_webhook_payload(
            event_type=event_type,
            event_id=generate_uuidv7(),
            occurred_at=datetime.now(UTC),
            tenant_id=doc.tenant_id,
            document_id=doc.id,
            status=status.value,
            external_ref=doc.external_ref,
            processing_result=doc.processing_result_json,
        )
        async with httpx.AsyncClient() as client:
            await deliver_webhook(
                http_client=client,
                url=url,
                secret=secret,
                payload=payload,
                max_attempts=settings.webhook_max_attempts,
                skip=skip,
                timeout_seconds=settings.webhook_timeout_seconds,
            )
    except Exception as exc:
        logger.error(
            "webhook_notify_failed",
            document_id=str(doc.id),
            status=status.value,
            error=str(exc),
        )


async def handle_processing_message(
    *,
    session: AsyncSession,
    settings: Settings,
    redis: RedisSetNx | None,
    hooks: tuple[VirusScanHook, OcrHook, ExtractHook],
    body: str,
) -> DocumentStatus:
    """Hooks → PROCESSED | FAILED; duplicate delivery short-circuits on terminal."""
    cache: RedisSetNx = redis if redis is not None else InMemoryRedisCache()
    parsed = parse_process_document_message(body)
    virus, ocr, extract = hooks

    doc = await _load_document(
        session,
        document_id=parsed.document_id,
        tenant_id=parsed.tenant_id,
    )
    tenant = await _load_tenant(session, parsed.tenant_id)
    tenant_slug = _tenant_slug_for_metrics(tenant)
    correlation_id = parsed.correlation_id or generate_uuidv7()
    current = DocumentStatus(doc.status)

    if current in _TERMINAL_STATUSES:
        # Already durable terminal — do not re-fire webhook (skip=True guard).
        if current in _TERMINAL_WEBHOOK_EVENTS:
            await _notify_terminal_webhook(
                session=session,
                settings=settings,
                doc=doc,
                status=current,
                skip=True,
            )
        return current

    locked = await acquire_processing_lock(cache, doc.id)
    if not locked:
        return DocumentStatus(doc.status)

    status = await run_processing_pipeline(
        session,
        doc,
        virus=virus,
        ocr=ocr,
        extract=extract,
        correlation_id=correlation_id,
        bucket=parsed.s3_bucket or (doc.s3_bucket or ""),
        key=parsed.s3_key or (doc.s3_key or ""),
        tenant_slug=tenant_slug,
    )
    if status in _TERMINAL_WEBHOOK_EVENTS:
        await _notify_terminal_webhook(
            session=session,
            settings=settings,
            doc=doc,
            status=status,
            skip=False,
        )
    return status
