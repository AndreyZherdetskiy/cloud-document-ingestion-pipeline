"""Append-only audit read/write (in-memory for unit; SQLAlchemy for runtime)."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.domain.enums import ActorType
from doc_pipeline.domain.errors import NotFoundError
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.audit_log import AuditLog
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.services.document_service import DocumentService


@dataclass
class AuditRecord:
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    job_id: uuid.UUID | None
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_type: ActorType
    actor_id: str | None
    correlation_id: uuid.UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _encode_cursor(created_at: datetime, event_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(event_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return datetime.fromisoformat(raw["t"]), uuid.UUID(raw["id"])


class AuditService(Protocol):
    async def append(self, record: AuditRecord) -> AuditRecord: ...

    async def list_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        from_ts: datetime | None,
        to_ts: datetime | None,
        event_type: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[AuditRecord], str | None]: ...

    async def recent_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        limit: int = 5,
    ) -> list[AuditRecord]: ...


class InMemoryAuditService:
    def __init__(self, document_service: DocumentService) -> None:
        self._documents = document_service
        self._events: list[AuditRecord] = []

    def seed(self, record: AuditRecord) -> None:
        self._events.append(record)

    async def append(self, record: AuditRecord) -> AuditRecord:
        self._events.append(record)
        return record

    async def list_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        from_ts: datetime | None,
        to_ts: datetime | None,
        event_type: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[AuditRecord], str | None]:
        await self._documents.get(tenant_id=tenant_id, document_id=document_id)
        items = [
            e for e in self._events if e.tenant_id == tenant_id and e.document_id == document_id
        ]
        if from_ts is not None:
            items = [e for e in items if e.created_at >= from_ts]
        if to_ts is not None:
            items = [e for e in items if e.created_at <= to_ts]
        if event_type is not None:
            items = [e for e in items if e.event_type == event_type]
        items.sort(key=lambda e: (e.created_at, e.id), reverse=True)
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            items = [e for e in items if (e.created_at, e.id) < (cursor_ts, cursor_id)]
        page = items[:limit]
        next_cursor = None
        if len(items) > limit:
            last = page[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return page, next_cursor

    async def recent_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        limit: int = 5,
    ) -> list[AuditRecord]:
        items, _ = await self.list_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
            from_ts=None,
            to_ts=None,
            event_type=None,
            cursor=None,
            limit=limit,
        )
        return items


class SqlAlchemyAuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_record(self, row: AuditLog) -> AuditRecord:
        return AuditRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            document_id=row.document_id,
            job_id=row.job_id,
            event_type=row.event_type,
            from_status=row.from_status,
            to_status=row.to_status,
            actor_type=ActorType(row.actor_type),
            actor_id=row.actor_id,
            correlation_id=row.correlation_id,
            created_at=row.created_at,
        )

    async def _ensure_document(self, *, tenant_id: uuid.UUID, document_id: uuid.UUID) -> None:
        row = await self._session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise NotFoundError("Document not found")

    async def append(self, record: AuditRecord) -> AuditRecord:
        row = AuditLog(
            id=record.id or generate_uuidv7(),
            tenant_id=record.tenant_id,
            document_id=record.document_id,
            job_id=record.job_id,
            event_type=record.event_type,
            from_status=record.from_status,
            to_status=record.to_status,
            actor_type=record.actor_type.value,
            actor_id=record.actor_id,
            correlation_id=record.correlation_id,
        )
        self._session.add(row)
        # Flush only — caller commits with the status mutation (ADR-003).
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_record(row)

    async def list_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        from_ts: datetime | None,
        to_ts: datetime | None,
        event_type: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[AuditRecord], str | None]:
        await self._ensure_document(tenant_id=tenant_id, document_id=document_id)
        stmt: Select[tuple[AuditLog]] = select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.document_id == document_id,
        )
        if from_ts is not None:
            stmt = stmt.where(AuditLog.created_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(AuditLog.created_at <= to_ts)
        if event_type is not None:
            stmt = stmt.where(AuditLog.event_type == event_type)
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            stmt = stmt.where(
                (AuditLog.created_at < cursor_ts)
                | ((AuditLog.created_at == cursor_ts) & (AuditLog.id < cursor_id))
            )
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
        rows = list((await self._session.scalars(stmt)).all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return [self._to_record(r) for r in rows], next_cursor

    async def recent_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        limit: int = 5,
    ) -> list[AuditRecord]:
        items, _ = await self.list_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
            from_ts=None,
            to_ts=None,
            event_type=None,
            cursor=None,
            limit=limit,
        )
        return items
