"""ADR-003: job retry/cancel + audit share one PostgreSQL commit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from doc_pipeline.domain.enums import ActorType, JobStatus, JobType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.job import Job
from doc_pipeline.domain.services.audit_service import AuditRecord, SqlAlchemyAuditService
from doc_pipeline.domain.services.job_service import SqlAlchemyJobService


class RecordingAsyncSession:
    """Minimal AsyncSession stand-in that counts commit/flush/add."""

    def __init__(self, *, job: Job, document: Document) -> None:
        self._job = job
        self._document = document
        self.commits = 0
        self.flushes = 0
        self.added: list[object] = []
        self.refresh_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, _obj: object) -> None:
        self.refresh_calls += 1

    async def scalar(self, stmt: object) -> Any | None:
        compiled = stmt.compile()  # type: ignore[attr-defined]
        text = str(compiled).lower()
        if "from jobs" in text or "join documents" in text:
            return self._job
        if "from documents" in text:
            return self._document
        return None


def _seed_failed_job() -> tuple[RecordingAsyncSession, UUID, UUID, UUID]:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    job_id = generate_uuidv7()
    document = Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type="INVOICE",
        status="UPLOADED",
        idempotency_key="idem-gap2",
    )
    job = Job(
        id=job_id,
        document_id=doc_id,
        job_type=JobType.INGESTION.value,
        status=JobStatus.FAILED.value,
        attempt=2,
        max_attempts=5,
        created_at=datetime.now(UTC),
    )
    session = RecordingAsyncSession(job=job, document=document)
    return session, tenant_id, doc_id, job_id


async def _retry_with_audit(
    session: RecordingAsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
) -> None:
    """Mirror api/v1/jobs.retry_job unit-of-work (status + audit, one commit)."""
    jobs = SqlAlchemyJobService(session)  # type: ignore[arg-type]
    audit = SqlAlchemyAuditService(session)  # type: ignore[arg-type]
    before = await jobs.get(tenant_id=tenant_id, job_id=job_id)
    record = await jobs.retry(tenant_id=tenant_id, job_id=job_id)
    await audit.append(
        AuditRecord(
            id=generate_uuidv7(),
            tenant_id=tenant_id,
            document_id=record.document_id,
            job_id=record.id,
            event_type="JOB_RETRY",
            from_status=before.status.value,
            to_status=record.status.value,
            actor_type=ActorType.OPERATOR,
            actor_id="operator-1",
            correlation_id=generate_uuidv7(),
        )
    )
    await session.commit()


async def _cancel_with_audit(
    session: RecordingAsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
) -> None:
    jobs = SqlAlchemyJobService(session)  # type: ignore[arg-type]
    audit = SqlAlchemyAuditService(session)  # type: ignore[arg-type]
    before = await jobs.get(tenant_id=tenant_id, job_id=job_id)
    record = await jobs.cancel(tenant_id=tenant_id, job_id=job_id)
    await audit.append(
        AuditRecord(
            id=generate_uuidv7(),
            tenant_id=tenant_id,
            document_id=record.document_id,
            job_id=record.id,
            event_type="JOB_CANCEL",
            from_status=before.status.value,
            to_status=record.status.value,
            actor_type=ActorType.OPERATOR,
            actor_id="operator-1",
            correlation_id=generate_uuidv7(),
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_retry_and_audit_exactly_one_commit() -> None:
    session, tenant_id, _doc_id, job_id = _seed_failed_job()
    await _retry_with_audit(session, tenant_id=tenant_id, job_id=job_id)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_cancel_and_audit_exactly_one_commit() -> None:
    session, tenant_id, _doc_id, job_id = _seed_failed_job()
    await _cancel_with_audit(session, tenant_id=tenant_id, job_id=job_id)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_append_failure_skips_commit() -> None:
    session, tenant_id, _doc_id, job_id = _seed_failed_job()
    jobs = SqlAlchemyJobService(session)  # type: ignore[arg-type]
    audit = SqlAlchemyAuditService(session)  # type: ignore[arg-type]
    before = await jobs.get(tenant_id=tenant_id, job_id=job_id)
    record = await jobs.retry(tenant_id=tenant_id, job_id=job_id)
    assert session.commits == 0

    async def _boom(_record: AuditRecord) -> AuditRecord:
        raise RuntimeError("audit insert failed")

    audit.append = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="audit insert failed"):
        await audit.append(
            AuditRecord(
                id=generate_uuidv7(),
                tenant_id=tenant_id,
                document_id=record.document_id,
                job_id=record.id,
                event_type="JOB_RETRY",
                from_status=before.status.value,
                to_status=record.status.value,
                actor_type=ActorType.OPERATOR,
                actor_id="operator-1",
                correlation_id=generate_uuidv7(),
            )
        )
    assert session.commits == 0
