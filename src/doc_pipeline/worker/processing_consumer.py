"""Processing SQS long-poll: PROCESS_DOCUMENT → hooks → terminal status.

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
from doc_pipeline.domain.hooks.base import ExtractHook, OcrHook, VirusScanHook
from doc_pipeline.domain.hooks.factory import build_hooks
from doc_pipeline.domain.services.idempotency import RedisSetNx
from doc_pipeline.infrastructure.aws.sqs import get_sqs_client
from doc_pipeline.infrastructure.cache.redis import RedisRateLimitClient
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker
from doc_pipeline.logging import configure_logging
from doc_pipeline.observability.otel import configure_otel, shutdown_otel
from doc_pipeline.worker.events import parse_process_document_message
from doc_pipeline.worker.processing_handlers import handle_processing_message

logger = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)

_stop = asyncio.Event()

_TERMINAL_ACK = frozenset(
    {
        DocumentStatus.PROCESSED,
        DocumentStatus.FAILED,
        DocumentStatus.CANCELLED,
    }
)


def _request_stop(*_args: object) -> None:
    _stop.set()


def delete_message(client: BaseClient, *, queue_url: str, receipt_handle: str) -> None:
    client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


async def _handle_one_message(
    *,
    sqs: BaseClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    hooks: tuple[VirusScanHook, OcrHook, ExtractHook],
    redis: RedisSetNx | None,
    body: str,
    receipt: str,
) -> None:
    with _tracer.start_as_current_span(
        "process.handle_message",
        attributes={"messaging.system": "aws.sqs"},
    ):
        status: DocumentStatus | None = None
        try:
            parsed = parse_process_document_message(body)
            span = trace.get_current_span()
            span.set_attribute("document_id", str(parsed.document_id))
            async with session_factory() as session:
                status = await handle_processing_message(
                    session=session,
                    settings=settings,
                    redis=redis,
                    hooks=hooks,
                    body=body,
                )
            span.set_attribute("document.status", status.value)
            logger.info("processing_message_handled", status=status.value)
        except Exception:
            logger.exception("processing_message_handler_failed")
            return
        if status in _TERMINAL_ACK:
            await asyncio.to_thread(
                delete_message,
                sqs,
                queue_url=settings.sqs_processing_queue_url,
                receipt_handle=receipt,
            )


async def run_once(
    *,
    sqs: BaseClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    hooks: tuple[VirusScanHook, OcrHook, ExtractHook],
    redis: RedisSetNx | None = None,
) -> bool:
    """Receive a batch; ACK each message only after durable terminal status."""
    if _stop.is_set():
        return False
    response: dict[str, Any] = await asyncio.to_thread(
        sqs.receive_message,
        QueueUrl=settings.sqs_processing_queue_url,
        MaxNumberOfMessages=settings.sqs_max_number_of_messages,
        WaitTimeSeconds=10,
        VisibilityTimeout=settings.sqs_visibility_timeout_seconds,
    )
    messages = response.get("Messages") or []
    for message in messages:
        await _handle_one_message(
            sqs=sqs,
            session_factory=session_factory,
            settings=settings,
            hooks=hooks,
            redis=redis,
            body=str(message["Body"]),
            receipt=str(message["ReceiptHandle"]),
        )
        if _stop.is_set():
            break
    return True


async def run_processing_worker(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    configure_logging(cfg)
    configure_otel("doc-pipeline-processing-worker", cfg)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, _request_stop)

    sqs = get_sqs_client(cfg)
    session_factory = get_async_sessionmaker(cfg)
    hooks = build_hooks(cfg)
    redis = RedisRateLimitClient(cfg.redis_url)
    try:
        while not _stop.is_set():
            await run_once(
                sqs=sqs,
                session_factory=session_factory,
                settings=cfg,
                hooks=hooks,
                redis=redis,
            )
    finally:
        await redis.close()
        shutdown_otel()
