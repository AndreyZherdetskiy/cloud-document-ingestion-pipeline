"""Document create/list/get service (in-memory for unit; SQLAlchemy for runtime)."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.errors import ConflictError, NotFoundError
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.schemas.documents import DocumentCreate
from doc_pipeline.domain.state_machine import transition


@dataclass
class DocumentRecord:
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_type: DocumentType
    status: DocumentStatus
    external_ref: str | None
    idempotency_key: str
    title: str | None
    metadata: dict[str, Any]
    file_name: str | None
    mime_type: str | None
    checksum_sha256: str | None
    file_size_bytes: int | None
    created_by: str | None
    correlation_id: uuid.UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _payload_fingerprint(body: DocumentCreate) -> dict[str, Any]:
    return {
        "document_type": body.document_type.value,
        "external_ref": body.external_ref,
        "title": body.title,
        "metadata": body.metadata,
        "file_name": body.file_name,
        "content_type": body.content_type,
        "declared_size_bytes": body.declared_size_bytes,
        "checksum_sha256": body.checksum_sha256,
    }


def _record_fingerprint(record: DocumentRecord) -> dict[str, Any]:
    return {
        "document_type": (
            record.document_type.value
            if isinstance(record.document_type, DocumentType)
            else str(record.document_type)
        ),
        "external_ref": record.external_ref,
        "title": record.title,
        "metadata": record.metadata,
        "file_name": record.file_name,
        "content_type": record.mime_type,
        "declared_size_bytes": record.file_size_bytes,
        "checksum_sha256": record.checksum_sha256,
    }


def _encode_cursor(created_at: datetime, doc_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(doc_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return datetime.fromisoformat(raw["t"]), uuid.UUID(raw["id"])


class DocumentService(Protocol):
    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        created_by: str,
        correlation_id: uuid.UUID,
        idempotency_key: str,
        body: DocumentCreate,
    ) -> tuple[DocumentRecord, bool]:
        """Return (document, created). created=False → idempotent replay (HTTP 200)."""
        ...

    async def get(self, *, tenant_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRecord: ...

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        status: DocumentStatus | None,
        document_type: DocumentType | None,
        external_ref: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[DocumentRecord], str | None]: ...

    async def cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        reset_for_represign: bool = False,
    ) -> DocumentRecord: ...


class InMemoryDocumentService:
    """Unit-test store — no PostgreSQL."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, DocumentRecord] = {}
        self._by_idem: dict[tuple[uuid.UUID, str], uuid.UUID] = {}

    def seed(self, record: DocumentRecord) -> None:
        self._by_id[record.id] = record
        self._by_idem[(record.tenant_id, record.idempotency_key)] = record.id

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        created_by: str,
        correlation_id: uuid.UUID,
        idempotency_key: str,
        body: DocumentCreate,
    ) -> tuple[DocumentRecord, bool]:
        key = (tenant_id, idempotency_key)
        existing_id = self._by_idem.get(key)
        if existing_id is not None:
            existing = self._by_id[existing_id]
            if _record_fingerprint(existing) != _payload_fingerprint(body):
                raise ConflictError(
                    "Idempotency-Key already used with a different payload",
                )
            return existing, False

        record = DocumentRecord(
            id=generate_uuidv7(),
            tenant_id=tenant_id,
            document_type=body.document_type,
            status=DocumentStatus.DRAFT,
            external_ref=body.external_ref,
            idempotency_key=idempotency_key,
            title=body.title,
            metadata=dict(body.metadata),
            file_name=body.file_name,
            mime_type=body.content_type,
            checksum_sha256=body.checksum_sha256,
            file_size_bytes=body.declared_size_bytes,
            created_by=created_by,
            correlation_id=correlation_id,
        )
        self._by_id[record.id] = record
        self._by_idem[key] = record.id
        return record, True

    async def get(self, *, tenant_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRecord:
        record = self._by_id.get(document_id)
        if record is None or record.tenant_id != tenant_id:
            raise NotFoundError("Document not found")
        return record

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        status: DocumentStatus | None,
        document_type: DocumentType | None,
        external_ref: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[DocumentRecord], str | None]:
        items = [r for r in self._by_id.values() if r.tenant_id == tenant_id]
        if status is not None:
            items = [r for r in items if r.status == status]
        if document_type is not None:
            items = [r for r in items if r.document_type == document_type]
        if external_ref is not None:
            items = [r for r in items if r.external_ref == external_ref]
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

    async def cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        reset_for_represign: bool = False,
    ) -> DocumentRecord:
        record = await self.get(tenant_id=tenant_id, document_id=document_id)
        # Spec §10.3.8: after expired upload, reset to DRAFT so client can re-presign.
        if reset_for_represign and record.status is DocumentStatus.UPLOADING:
            record.status = DocumentStatus.DRAFT
            return record
        record.status = transition(record.status, DocumentStatus.CANCELLED)
        return record


class SqlAlchemyDocumentService:
    """PostgreSQL-backed document service (used when session is available)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_record(self, row: Document) -> DocumentRecord:
        return DocumentRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            document_type=DocumentType(row.document_type),
            status=DocumentStatus(row.status),
            external_ref=row.external_ref,
            idempotency_key=row.idempotency_key,
            title=row.title,
            metadata=dict(row.metadata_json or {}),
            file_name=row.file_name,
            mime_type=row.mime_type,
            checksum_sha256=row.checksum_sha256,
            file_size_bytes=row.file_size_bytes,
            created_by=row.created_by,
            correlation_id=uuid.UUID(int=0),  # not persisted on row; set by caller path
            created_at=row.created_at,
        )

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        created_by: str,
        correlation_id: uuid.UUID,
        idempotency_key: str,
        body: DocumentCreate,
    ) -> tuple[DocumentRecord, bool]:
        existing = await self._session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            record = self._to_record(existing)
            record.correlation_id = correlation_id
            if _record_fingerprint(record) != _payload_fingerprint(body):
                raise ConflictError(
                    "Idempotency-Key already used with a different payload",
                )
            return record, False

        row = Document(
            id=generate_uuidv7(),
            tenant_id=tenant_id,
            document_type=body.document_type.value,
            status=DocumentStatus.DRAFT.value,
            external_ref=body.external_ref,
            idempotency_key=idempotency_key,
            title=body.title,
            metadata_json=dict(body.metadata),
            file_name=body.file_name,
            mime_type=body.content_type,
            checksum_sha256=body.checksum_sha256,
            file_size_bytes=body.declared_size_bytes,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        record = self._to_record(row)
        record.correlation_id = correlation_id
        return record, True

    async def get(self, *, tenant_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRecord:
        row = await self._session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise NotFoundError("Document not found")
        return self._to_record(row)

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        status: DocumentStatus | None,
        document_type: DocumentType | None,
        external_ref: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[DocumentRecord], str | None]:
        stmt: Select[tuple[Document]] = select(Document).where(Document.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(Document.status == status.value)
        if document_type is not None:
            stmt = stmt.where(Document.document_type == document_type.value)
        if external_ref is not None:
            stmt = stmt.where(Document.external_ref == external_ref)
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            stmt = stmt.where(
                (Document.created_at < cursor_ts)
                | ((Document.created_at == cursor_ts) & (Document.id < cursor_id))
            )
        stmt = stmt.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)
        rows = list((await self._session.scalars(stmt)).all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return [self._to_record(r) for r in rows], next_cursor

    async def cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        reset_for_represign: bool = False,
    ) -> DocumentRecord:
        row = await self._session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise NotFoundError("Document not found")
        current = DocumentStatus(row.status)
        if reset_for_represign and current is DocumentStatus.UPLOADING:
            row.status = DocumentStatus.DRAFT.value
        else:
            row.status = transition(current, DocumentStatus.CANCELLED).value
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_record(row)


async def check_postgres_ready(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def postgres_scalar_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.now()))
    assert value is not None
    return value
