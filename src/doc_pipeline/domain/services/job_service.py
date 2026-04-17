"""Job get/list/retry/cancel service (in-memory for unit; SQLAlchemy for runtime)."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.domain.enums import JobStatus, JobType
from doc_pipeline.domain.errors import ConflictError, NotFoundError, ValidationError
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.job import Job

_RETRYABLE = frozenset({JobStatus.FAILED, JobStatus.STUCK})
_CANCELABLE = frozenset(
    {
        JobStatus.PENDING,
        JobStatus.RUNNING,
        JobStatus.FAILED,
        JobStatus.STUCK,
    }
)


@dataclass
class JobRecord:
    id: uuid.UUID
    document_id: uuid.UUID
    tenant_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    attempt: int = 1
    max_attempts: int = 5
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _encode_cursor(created_at: datetime, job_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(job_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return datetime.fromisoformat(raw["t"]), uuid.UUID(raw["id"])


def _parse_older_than(older_than: str | None) -> datetime | None:
    if older_than is None:
        return None
    text = older_than.strip().lower()
    if text.endswith("m"):
        minutes = int(text[:-1])
        return datetime.now(UTC) - timedelta(minutes=minutes)
    if text.endswith("h"):
        hours = int(text[:-1])
        return datetime.now(UTC) - timedelta(hours=hours)
    if text.endswith("s"):
        seconds = int(text[:-1])
        return datetime.now(UTC) - timedelta(seconds=seconds)
    raise ValidationError(f"Unsupported older_than format: {older_than!r}")


class JobService(Protocol):
    async def get(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord: ...

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        status: JobStatus | None,
        document_id: uuid.UUID | None,
        older_than: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[JobRecord], str | None]: ...

    async def retry(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord: ...

    async def cancel(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord: ...

    async def latest_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> JobRecord | None: ...


class InMemoryJobService:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, JobRecord] = {}

    def seed(self, record: JobRecord) -> None:
        self._by_id[record.id] = record

    async def get(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord:
        record = self._by_id.get(job_id)
        if record is None or record.tenant_id != tenant_id:
            raise NotFoundError("Job not found")
        return record

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        status: JobStatus | None,
        document_id: uuid.UUID | None,
        older_than: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[JobRecord], str | None]:
        cutoff = _parse_older_than(older_than)
        items = [r for r in self._by_id.values() if r.tenant_id == tenant_id]
        if status is not None:
            items = [r for r in items if r.status == status]
        if document_id is not None:
            items = [r for r in items if r.document_id == document_id]
        if cutoff is not None:
            items = [r for r in items if r.created_at <= cutoff]
        items.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            items = [r for r in items if (r.created_at, r.id) < (cursor_ts, cursor_id)]
        page = items[:limit]
        next_cursor = None
        if len(items) > limit:
            last = page[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return page, next_cursor

    async def retry(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord:
        record = await self.get(tenant_id=tenant_id, job_id=job_id)
        if record.status not in _RETRYABLE:
            raise ConflictError(
                f"Job status {record.status} cannot be retried (only FAILED/STUCK)",
            )
        record.status = JobStatus.PENDING
        record.attempt += 1
        record.error_code = None
        record.error_message = None
        record.finished_at = None
        return record

    async def cancel(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord:
        record = await self.get(tenant_id=tenant_id, job_id=job_id)
        if record.status not in _CANCELABLE:
            raise ConflictError(f"Job status {record.status} cannot be cancelled")
        record.status = JobStatus.CANCELLED
        record.finished_at = datetime.now(UTC)
        return record

    async def latest_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> JobRecord | None:
        items = [
            r
            for r in self._by_id.values()
            if r.tenant_id == tenant_id and r.document_id == document_id
        ]
        if not items:
            return None
        items.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return items[0]


class SqlAlchemyJobService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_record(self, row: Job, tenant_id: uuid.UUID) -> JobRecord:
        return JobRecord(
            id=row.id,
            document_id=row.document_id,
            tenant_id=tenant_id,
            job_type=JobType(row.job_type),
            status=JobStatus(row.status),
            attempt=row.attempt,
            max_attempts=row.max_attempts,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    async def _tenant_scoped_job(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> Job:
        row = await self._session.scalar(
            select(Job)
            .join(Document, Document.id == Job.document_id)
            .where(Job.id == job_id, Document.tenant_id == tenant_id)
        )
        if row is None:
            raise NotFoundError("Job not found")
        return row

    async def get(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord:
        row = await self._tenant_scoped_job(tenant_id=tenant_id, job_id=job_id)
        return self._to_record(row, tenant_id)

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        status: JobStatus | None,
        document_id: uuid.UUID | None,
        older_than: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[JobRecord], str | None]:
        cutoff = _parse_older_than(older_than)
        stmt: Select[tuple[Job]] = (
            select(Job)
            .join(Document, Document.id == Job.document_id)
            .where(Document.tenant_id == tenant_id)
        )
        if status is not None:
            stmt = stmt.where(Job.status == status.value)
        if document_id is not None:
            stmt = stmt.where(Job.document_id == document_id)
        if cutoff is not None:
            stmt = stmt.where(Job.created_at <= cutoff)
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            stmt = stmt.where(
                (Job.created_at < cursor_ts)
                | ((Job.created_at == cursor_ts) & (Job.id < cursor_id))
            )
        stmt = stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
        rows = list((await self._session.scalars(stmt)).all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return [self._to_record(r, tenant_id) for r in rows], next_cursor

    async def retry(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord:
        row = await self._tenant_scoped_job(tenant_id=tenant_id, job_id=job_id)
        status = JobStatus(row.status)
        if status not in _RETRYABLE:
            raise ConflictError(
                f"Job status {status} cannot be retried (only FAILED/STUCK)",
            )
        row.status = JobStatus.PENDING.value
        row.attempt += 1
        row.error_code = None
        row.error_message = None
        row.finished_at = None
        # Flush only — caller commits with audit in one transaction (ADR-003).
        await self._session.flush()
        return self._to_record(row, tenant_id)

    async def cancel(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord:
        row = await self._tenant_scoped_job(tenant_id=tenant_id, job_id=job_id)
        status = JobStatus(row.status)
        if status not in _CANCELABLE:
            raise ConflictError(f"Job status {status} cannot be cancelled")
        row.status = JobStatus.CANCELLED.value
        row.finished_at = datetime.now(UTC)
        # Flush only — caller commits with audit in one transaction (ADR-003).
        await self._session.flush()
        return self._to_record(row, tenant_id)

    async def latest_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> JobRecord | None:
        row = await self._session.scalar(
            select(Job)
            .join(Document, Document.id == Job.document_id)
            .where(Job.document_id == document_id, Document.tenant_id == tenant_id)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return self._to_record(row, tenant_id)
