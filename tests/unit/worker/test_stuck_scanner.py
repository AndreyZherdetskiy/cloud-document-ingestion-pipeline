"""Stuck-job scanner: RUNNING → STUCK; stale QUEUED → PROCESS_DOCUMENT re-enqueue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType, JobStatus, JobType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.worker.events import parse_process_document_message
from doc_pipeline.worker.stuck_scanner import (
    mark_stuck_jobs,
    reenqueue_stale_queued_documents,
)


class _FakeJob:
    def __init__(self, status: str, started_at: datetime) -> None:
        self.id = uuid4()
        self.status = status
        self.started_at = started_at


class _ScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return list(self._items)

    def __iter__(self):
        return iter(self._items)

    def scalar_one_or_none(self) -> object | None:
        return self._items[0] if self._items else None


class _MarkStuckFakeSession:
    def __init__(
        self,
        jobs: list[_FakeJob],
        *,
        now: datetime,
        older_than: timedelta,
    ) -> None:
        self.jobs = jobs
        self.committed = False
        self._cutoff = now - older_than

    async def execute(self, *_a: object, **_k: object) -> _ScalarResult:
        matched = [
            j
            for j in self.jobs
            if j.status in (JobStatus.PENDING, JobStatus.RUNNING)
            and j.started_at is not None
            and j.started_at < self._cutoff
        ]
        return _ScalarResult(matched)

    async def commit(self) -> None:
        self.committed = True


class _FakeDocument:
    def __init__(
        self,
        *,
        status: str,
        updated_at: datetime,
        tenant_id: UUID | None = None,
        document_type: str = DocumentType.INVOICE.value,
        s3_bucket: str = "dev-doc-pipeline",
        s3_key: str = "t/d/file.pdf",
    ) -> None:
        self.id = uuid4()
        self.tenant_id = tenant_id or uuid4()
        self.status = status
        self.updated_at = updated_at
        self.document_type = document_type
        self.s3_bucket = s3_bucket
        self.s3_key = s3_key


class _FakeProcessingJob:
    def __init__(self, *, document_id: UUID, status: str = JobStatus.PENDING.value) -> None:
        self.id = uuid4()
        self.document_id = document_id
        self.job_type = JobType.PROCESSING.value
        self.status = status
        self.attempt = 1
        self.created_at = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)


class _ReenqueueFakeSession:
    def __init__(
        self,
        documents: list[_FakeDocument],
        jobs: list[_FakeProcessingJob],
        *,
        now: datetime,
        older_than: timedelta,
    ) -> None:
        self.documents = documents
        self.jobs = jobs
        self._cutoff = now - older_than
        self._query = 0

    async def execute(self, *_a: object, **_k: object) -> _ScalarResult:
        self._query += 1
        if self._query == 1:
            matched = [
                d
                for d in self.documents
                if d.status == DocumentStatus.QUEUED and d.updated_at < self._cutoff
            ]
            return _ScalarResult(matched)
        doc = self.documents[0] if self.documents else None
        if doc is None:
            return _ScalarResult([])
        matched = [
            j
            for j in self.jobs
            if j.document_id == doc.id
            and j.job_type == JobType.PROCESSING.value
            and j.status in (JobStatus.PENDING, JobStatus.RUNNING)
        ]
        return _ScalarResult(matched[:1])


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
async def test_mark_stuck_jobs_updates_old_running() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    old = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=45))
    fresh = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=5))
    done = _FakeJob(JobStatus.SUCCEEDED, now - timedelta(hours=2))
    session = _MarkStuckFakeSession(
        [old, fresh, done],
        now=now,
        older_than=timedelta(minutes=30),
    )
    n = await mark_stuck_jobs(
        session=session,  # type: ignore[arg-type]
        older_than=timedelta(minutes=30),
        now=now,
    )
    assert n == 1
    assert old.status == JobStatus.STUCK
    assert fresh.status == JobStatus.RUNNING
    assert done.status == JobStatus.SUCCEEDED
    assert session.committed is True


@pytest.mark.asyncio
async def test_mark_stuck_jobs_green() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    old = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=45))
    fresh = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=5))
    done = _FakeJob(JobStatus.SUCCEEDED, now - timedelta(hours=2))
    already = _FakeJob(JobStatus.STUCK, now - timedelta(hours=1))
    session = _MarkStuckFakeSession(
        [old, fresh, done, already],
        now=now,
        older_than=timedelta(minutes=30),
    )
    n = await mark_stuck_jobs(
        session=session,  # type: ignore[arg-type]
        older_than=timedelta(minutes=30),
        now=now,
    )
    assert n == 1
    assert old.status == JobStatus.STUCK
    assert fresh.status == JobStatus.RUNNING
    assert done.status == JobStatus.SUCCEEDED
    assert already.status == JobStatus.STUCK
    assert session.committed is True


@pytest.mark.asyncio
async def test_reenqueue_stale_queued_sends_one_process_document() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    stale = _FakeDocument(
        status=DocumentStatus.QUEUED,
        updated_at=now - timedelta(minutes=45),
        tenant_id=tenant_id,
        s3_key=f"{tenant_id}/{doc_id}/invoice.pdf",
    )
    stale.id = doc_id
    fresh = _FakeDocument(
        status=DocumentStatus.QUEUED,
        updated_at=now - timedelta(minutes=5),
    )
    done = _FakeDocument(
        status=DocumentStatus.PROCESSED,
        updated_at=now - timedelta(hours=2),
    )
    job = _FakeProcessingJob(document_id=doc_id)
    session = _ReenqueueFakeSession(
        [stale, fresh, done],
        [job],
        now=now,
        older_than=timedelta(minutes=30),
    )
    sqs = MagicMock()
    settings = _settings()

    n = await reenqueue_stale_queued_documents(
        session=session,  # type: ignore[arg-type]
        settings=settings,
        sqs_client=sqs,
        older_than=timedelta(minutes=30),
        now=now,
    )

    assert n == 1
    sqs.send_message.assert_called_once()
    call_kwargs = sqs.send_message.call_args.kwargs
    assert call_kwargs["QueueUrl"] == settings.sqs_processing_queue_url
    parsed = parse_process_document_message(call_kwargs["MessageBody"])
    assert parsed.message_type == "PROCESS_DOCUMENT"
    assert parsed.document_id == doc_id
    assert parsed.tenant_id == tenant_id
    assert parsed.job_id == job.id


@pytest.mark.asyncio
async def test_reenqueue_stale_queued_no_send_when_fresh() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    fresh = _FakeDocument(
        status=DocumentStatus.QUEUED,
        updated_at=now - timedelta(minutes=5),
    )
    session = _ReenqueueFakeSession(
        [fresh],
        [],
        now=now,
        older_than=timedelta(minutes=30),
    )
    sqs = MagicMock()

    n = await reenqueue_stale_queued_documents(
        session=session,  # type: ignore[arg-type]
        settings=_settings(),
        sqs_client=sqs,
        older_than=timedelta(minutes=30),
        now=now,
    )

    assert n == 0
    sqs.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_mark_stuck_jobs_no_commit_when_none_matched() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    fresh = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=5))
    session = _MarkStuckFakeSession(
        [fresh],
        now=now,
        older_than=timedelta(minutes=30),
    )
    n = await mark_stuck_jobs(
        session=session,  # type: ignore[arg-type]
        older_than=timedelta(minutes=30),
        now=now,
    )
    assert n == 0
    assert fresh.status == JobStatus.RUNNING
    assert session.committed is False
