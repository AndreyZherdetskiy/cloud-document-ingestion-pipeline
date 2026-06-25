"""Consumers must pass Settings.sqs_visibility_timeout_seconds to ReceiveMessage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.worker import consumer, ingestion_consumer, processing_consumer


def _session_factory() -> MagicMock:
    factory = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = ctx
    return factory


@pytest.mark.asyncio
async def test_ingestion_receive_message_uses_settings_visibility_timeout() -> None:
    ingestion_consumer._stop.clear()
    settings = Settings(otel_sdk_disabled=True)
    sqs = MagicMock()
    with patch(
        "doc_pipeline.worker.ingestion_consumer.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value={},
    ) as to_thread:
        await ingestion_consumer.run_once(
            sqs=sqs,
            session_factory=_session_factory(),
            settings=settings,
        )
    assert to_thread.await_args is not None
    assert to_thread.await_args.args[0] is sqs.receive_message
    assert to_thread.await_args.kwargs["VisibilityTimeout"] == 300
    assert to_thread.await_args.kwargs["VisibilityTimeout"] == (
        settings.sqs_visibility_timeout_seconds
    )


@pytest.mark.asyncio
async def test_processing_receive_message_uses_settings_visibility_timeout() -> None:
    processing_consumer._stop.clear()
    settings = Settings(otel_sdk_disabled=True)
    sqs = MagicMock()
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    with patch(
        "doc_pipeline.worker.processing_consumer.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value={},
    ) as to_thread:
        await processing_consumer.run_once(
            sqs=sqs,
            session_factory=_session_factory(),
            settings=settings,
            hooks=hooks,
        )
    assert to_thread.await_args is not None
    assert to_thread.await_args.args[0] is sqs.receive_message
    assert to_thread.await_args.kwargs["VisibilityTimeout"] == 300
    assert to_thread.await_args.kwargs["VisibilityTimeout"] == (
        settings.sqs_visibility_timeout_seconds
    )


@pytest.mark.asyncio
async def test_legacy_consumer_receive_message_uses_settings_visibility_timeout() -> None:
    consumer._stop.clear()
    settings = Settings(otel_sdk_disabled=True)
    sqs = MagicMock()
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    with patch(
        "doc_pipeline.worker.consumer.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value={},
    ) as to_thread:
        await consumer.run_once(
            sqs=sqs,
            session_factory=_session_factory(),
            settings=settings,
            hooks=hooks,
        )
    assert to_thread.await_args is not None
    assert to_thread.await_args.args[0] is sqs.receive_message
    assert to_thread.await_args.kwargs["VisibilityTimeout"] == 300
    assert to_thread.await_args.kwargs["VisibilityTimeout"] == (
        settings.sqs_visibility_timeout_seconds
    )


def test_settings_sqs_visibility_timeout_default_is_300() -> None:
    assert Settings().sqs_visibility_timeout_seconds == 300
