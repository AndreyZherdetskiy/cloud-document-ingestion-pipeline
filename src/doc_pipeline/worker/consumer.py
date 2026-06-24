"""SQS long-poll consumer loop.

SIGTERM: finish the in-flight message (commit + delete) or return without delete so
visibility timeout requeues it — never leave a half-applied terminal state unacked.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from botocore.client import BaseClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from doc_pipeline.config.settings import Settings, get_settings
from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.services.idempotency import RedisSetNx
from doc_pipeline.infrastructure.aws.sqs import get_sqs_client
from doc_pipeline.infrastructure.cache.redis import RedisRateLimitClient
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker
from doc_pipeline.logging import configure_logging
from doc_pipeline.observability.otel import configure_otel, shutdown_otel
from doc_pipeline.worker.events import parse_s3_event_message
from doc_pipeline.worker.handlers import handle_ingest_event

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


def _build_hooks(settings: Settings) -> tuple[StubVirusScanHook, StubOcrHook, StubExtractHook]:
    return (
        StubVirusScanHook(clean=settings.stub_virus_clean),
        StubOcrHook(),
        StubExtractHook(),
    )


def delete_message(client: BaseClient, *, queue_url: str, receipt_handle: str) -> None:
    client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


async def process_sqs_message(
    *,
    session: AsyncSession,
    hooks: tuple[StubVirusScanHook, StubOcrHook, StubExtractHook],
    settings: Settings,
    body: str,
    redis: RedisSetNx | None = None,
) -> DocumentStatus:
    event = parse_s3_event_message(body)
    return await handle_ingest_event(session, hooks, event, settings, redis=redis)


async def run_once(
    *,
    sqs: BaseClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    hooks: tuple[StubVirusScanHook, StubOcrHook, StubExtractHook],
    redis: RedisSetNx | None = None,
) -> bool:
    """Receive up to one message. Returns False when the stop event is set mid-idle."""
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
    async with session_factory() as session:
        status = await process_sqs_message(
            session=session,
            hooks=hooks,
            settings=settings,
            body=body,
            redis=redis,
        )
    # Delete after success or after terminal FAILED/CANCELLED is committed (spec poison).
    if status in _TERMINAL_ACK:
        await asyncio.to_thread(
            delete_message,
            sqs,
            queue_url=settings.sqs_queue_url,
            receipt_handle=receipt,
        )
    return True


async def run_worker(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    configure_logging(cfg)
    # Worker service name is independent of the API default in Settings.
    configure_otel("doc-pipeline-worker", cfg)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, _request_stop)

    sqs = get_sqs_client(cfg)
    session_factory = get_async_sessionmaker(cfg)
    hooks = _build_hooks(cfg)
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
