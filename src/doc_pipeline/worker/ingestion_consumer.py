"""Ingestion SQS long-poll: S3 events → QUEUED + PROCESS_DOCUMENT enqueue.

SIGTERM: finish the in-flight message (commit + delete) or return without delete so
visibility timeout requeues it — never leave a half-applied terminal state unacked.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

import structlog
from botocore.client import BaseClient
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from doc_pipeline.config.settings import Settings, get_settings
from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.services.idempotency import RedisSetNx
from doc_pipeline.infrastructure.aws.sqs import get_sqs_client
from doc_pipeline.infrastructure.cache.redis import RedisRateLimitClient
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker
from doc_pipeline.logging import configure_logging
from doc_pipeline.observability.otel import configure_otel, shutdown_otel
from doc_pipeline.worker.events import IgnorableSqsPayload, parse_s3_event_message
from doc_pipeline.worker.ingestion_handlers import handle_ingestion_event

logger = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)

_stop = asyncio.Event()

_ACK_STATUSES = frozenset(
    {
        DocumentStatus.QUEUED,
        DocumentStatus.PROCESSED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    }
)


def _request_stop(*_args: object) -> None:
    _stop.set()


def delete_message(client: BaseClient, *, queue_url: str, receipt_handle: str) -> None:
    client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


async def run_once(
    *,
    sqs: BaseClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    redis: RedisSetNx | None = None,
) -> bool:
    """Receive up to one ingest message. Returns False when stop is set mid-idle."""
    if _stop.is_set():
        return False
    response: dict[str, Any] = await asyncio.to_thread(
        sqs.receive_message,
        QueueUrl=settings.sqs_queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=10,
        VisibilityTimeout=settings.sqs_visibility_timeout_seconds,
    )
    messages = response.get("Messages") or []
    if not messages:
        return True
    message = messages[0]
    body = str(message["Body"])
    receipt = str(message["ReceiptHandle"])
    with _tracer.start_as_current_span(
        "ingest.handle_message",
        attributes={"messaging.system": "aws.sqs"},
    ):
        status: DocumentStatus | None = None
        try:
            async with session_factory() as session:
                status = await handle_ingestion_event(
                    session=session,
                    settings=settings,
                    redis=redis,
                    sqs_client=sqs,
                    body=body,
                )
        except IgnorableSqsPayload:
            trace.get_current_span().set_attribute("ignored", "test_event")
            logger.info("ingestion_test_event_acked")
            await asyncio.to_thread(
                delete_message,
                sqs,
                queue_url=settings.sqs_queue_url,
                receipt_handle=receipt,
            )
            return True
        except Exception:
            logger.exception("ingestion_message_handler_failed")
            return True

        span = trace.get_current_span()
        span.set_attribute("document.status", status.value)
        logger.info("ingestion_event_handled", status=status.value)
        try:
            parsed = parse_s3_event_message(body)
            span.set_attribute("document_id", str(parsed.document_id))
        except (IgnorableSqsPayload, ValueError):
            pass

    if status in _ACK_STATUSES:
        await asyncio.to_thread(
            delete_message,
            sqs,
            queue_url=settings.sqs_queue_url,
            receipt_handle=receipt,
        )
    return True


async def run_ingestion_worker(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    configure_logging(cfg)
    configure_otel("doc-pipeline-ingestion-worker", cfg)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, _request_stop)

    sqs = get_sqs_client(cfg)
    session_factory = get_async_sessionmaker(cfg)
    redis = RedisRateLimitClient(cfg.redis_url)
    try:
        while not _stop.is_set():
            await run_once(
                sqs=sqs,
                session_factory=session_factory,
                settings=cfg,
                redis=redis,
            )
    finally:
        await redis.close()
        shutdown_otel()
