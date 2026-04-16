"""Duplicate SQS delivery idempotency + moto poison → DLQ (ADR-002)."""

from __future__ import annotations

import json
import time

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
from doc_pipeline.domain.services.idempotency import acquire_processing_lock
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
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


@pytest.fixture
def redis() -> InMemoryRedisCache:
    return InMemoryRedisCache()


@pytest.fixture
def hooks_clean() -> tuple[StubVirusScanHook, StubOcrHook, StubExtractHook]:
    return (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())


@pytest.mark.asyncio
async def test_acquire_processing_lock_set_nx() -> None:
    cache = InMemoryRedisCache()
    doc_id = generate_uuidv7()
    assert await acquire_processing_lock(cache, doc_id, ttl_seconds=600) is True
    assert await acquire_processing_lock(cache, doc_id, ttl_seconds=600) is False


@pytest.mark.asyncio
async def test_duplicate_delivery_one_processed(
    db_session: FakeWorkerSession,
    redis: InMemoryRedisCache,
    uploaded_document: Document,
    settings: Settings,
    hooks_clean: tuple[StubVirusScanHook, StubOcrHook, StubExtractHook],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real_scan = hooks_clean[0].scan

    async def counting_scan(ctx: object) -> object:
        calls["n"] += 1
        return await real_scan(ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(hooks_clean[0], "scan", counting_scan)
    event = event_for(uploaded_document)
    s1 = await handle_ingest_event(
        db_session,  # type: ignore[arg-type]
        hooks_clean,
        event,
        settings,
        redis=redis,
    )
    s2 = await handle_ingest_event(
        db_session,  # type: ignore[arg-type]
        hooks_clean,
        event,
        settings,
        redis=redis,
    )
    assert s1 is DocumentStatus.PROCESSED
    assert s2 is DocumentStatus.PROCESSED
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_lock_not_acquired_skips_hooks_returns_current(
    redis: InMemoryRedisCache,
    settings: Settings,
    hooks_clean: tuple[StubVirusScanHook, StubOcrHook, StubExtractHook],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    doc = Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.SCANNING.value,
        idempotency_key=f"idem-{doc_id}",
        s3_bucket="dev-doc-pipeline",
        s3_key=f"{tenant_id}/{doc_id}/invoice.pdf",
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
    )
    tenant = Tenant(id=tenant_id, name="Acme", slug="acme", config_json={})
    session = FakeWorkerSession(doc, tenant)
    assert await acquire_processing_lock(redis, doc_id) is True

    calls = {"n": 0}
    real_scan = hooks_clean[0].scan

    async def counting_scan(ctx: object) -> object:
        calls["n"] += 1
        return await real_scan(ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(hooks_clean[0], "scan", counting_scan)
    status = await handle_ingest_event(
        session,  # type: ignore[arg-type]
        hooks_clean,
        event_for(doc),
        settings,
        redis=redis,
    )
    assert status is DocumentStatus.SCANNING
    assert calls["n"] == 0
    assert doc.status == DocumentStatus.SCANNING.value


def test_poison_message_lands_on_dlq_after_max_receive() -> None:
    """Moto RedrivePolicy: 5 receives without delete → DLQ (no terminal write)."""
    with mock_aws():
        sqs = boto3.client("sqs", region_name="eu-central-1")
        dlq_url = sqs.create_queue(QueueName="poison-dlq")["QueueUrl"]
        dlq_arn = sqs.get_queue_attributes(
            QueueUrl=dlq_url,
            AttributeNames=["QueueArn"],
        )["Attributes"]["QueueArn"]
        redrive = json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "5"})
        main_url = sqs.create_queue(
            QueueName="poison-main",
            Attributes={
                "VisibilityTimeout": "0",
                "RedrivePolicy": redrive,
            },
        )["QueueUrl"]
        sqs.send_message(QueueUrl=main_url, MessageBody="poison-handler-failure")

        for _ in range(5):
            resp = sqs.receive_message(
                QueueUrl=main_url,
                MaxNumberOfMessages=1,
                VisibilityTimeout=0,
                WaitTimeSeconds=0,
                AttributeNames=["All"],
            )
            assert resp.get("Messages"), "expected message still on main queue"
            # Simulate handler failure without terminal write: do not delete.

        deadline = time.time() + 5
        dlq_depth = 0
        while time.time() < deadline:
            dlq_depth = int(
                sqs.get_queue_attributes(
                    QueueUrl=dlq_url,
                    AttributeNames=["ApproximateNumberOfMessages"],
                )["Attributes"]["ApproximateNumberOfMessages"]
            )
            if dlq_depth >= 1:
                break
            time.sleep(0.05)
            # Nudge visibility so moto applies redrive after the 5th receive.
            sqs.receive_message(
                QueueUrl=main_url,
                MaxNumberOfMessages=1,
                VisibilityTimeout=0,
                WaitTimeSeconds=0,
            )
        assert dlq_depth >= 1
