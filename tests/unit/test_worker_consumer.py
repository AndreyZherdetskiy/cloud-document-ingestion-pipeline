"""Moto unit tests for SQS consumer delete-after-terminal policy."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import boto3
import pytest
from moto import mock_aws
from tests.fixtures.worker_session import FakeWorkerSession, event_for

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.worker import consumer
from doc_pipeline.worker.consumer import run_once


def _queue_depth(sqs: object, queue_url: str) -> int:
    attrs = sqs.get_queue_attributes(  # type: ignore[attr-defined]
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    return int(attrs["Attributes"]["ApproximateNumberOfMessages"])


def _session_factory(session: FakeWorkerSession) -> MagicMock:
    factory = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = ctx
    return factory


def _uploaded_doc() -> tuple[Document, Tenant]:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    doc = Document(
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
    return doc, tenant


@pytest.mark.asyncio
async def test_run_once_deletes_message_on_processed() -> None:
    with mock_aws():
        consumer._stop.clear()
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="test-ingest-processed")["QueueUrl"]
        doc, tenant = _uploaded_doc()
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(event_for(doc)))
        settings = Settings(sqs_queue_url=queue_url, otel_sdk_disabled=True)
        hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
        session = FakeWorkerSession(doc, tenant)
        order: list[str] = []
        orig_commit = session.commit

        async def commit_and_record() -> None:
            order.append("commit")
            await orig_commit()

        session.commit = commit_and_record  # type: ignore[method-assign]
        orig_delete = consumer.delete_message

        def delete_and_record(*args: object, **kwargs: object) -> None:
            order.append("delete")
            orig_delete(*args, **kwargs)

        with patch("doc_pipeline.worker.consumer.delete_message", side_effect=delete_and_record):
            await run_once(
                sqs=sqs,
                session_factory=_session_factory(session),
                settings=settings,
                hooks=hooks,
            )
        assert _queue_depth(sqs, queue_url) == 0
        assert order[-1] == "delete"
        assert order[:-1]
        assert all(item == "commit" for item in order[:-1])


@pytest.mark.asyncio
async def test_run_once_deletes_message_on_failed() -> None:
    with mock_aws():
        consumer._stop.clear()
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="test-ingest-failed")["QueueUrl"]
        doc, tenant = _uploaded_doc()
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(event_for(doc)))
        settings = Settings(sqs_queue_url=queue_url, otel_sdk_disabled=True)
        hooks = (StubVirusScanHook(clean=False), StubOcrHook(), StubExtractHook())
        session = FakeWorkerSession(doc, tenant)
        await run_once(
            sqs=sqs,
            session_factory=_session_factory(session),
            settings=settings,
            hooks=hooks,
        )
        assert _queue_depth(sqs, queue_url) == 0


@pytest.mark.asyncio
async def test_run_once_keeps_message_when_handler_raises() -> None:
    with mock_aws():
        consumer._stop.clear()
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="test-ingest-raise")["QueueUrl"]
        doc, tenant = _uploaded_doc()
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(event_for(doc)))
        settings = Settings(sqs_queue_url=queue_url, otel_sdk_disabled=True)
        hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
        session = FakeWorkerSession(doc, tenant)

        async def scalar_missing(_stmt: object) -> None:
            return None

        session.scalar = scalar_missing  # type: ignore[method-assign]
        with patch("doc_pipeline.worker.consumer.delete_message") as delete_mock:
            result = await run_once(
                sqs=sqs,
                session_factory=_session_factory(session),
                settings=settings,
                hooks=hooks,
            )
            assert result is True
            delete_mock.assert_not_called()
