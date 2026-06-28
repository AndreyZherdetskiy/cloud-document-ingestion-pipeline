"""SqlAlchemyDocumentService.create: insert-first, UNIQUE replay, no refresh."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.errors import ConflictError
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.schemas.documents import DocumentCreate
from doc_pipeline.domain.services.document_service import SqlAlchemyDocumentService


def _body() -> DocumentCreate:
    return DocumentCreate(
        document_type=DocumentType.INVOICE,
        file_name="a.pdf",
        content_type="application/pdf",
        checksum_sha256="a" * 64,
    )


def _row(*, tenant_id: UUID, idempotency_key: str, file_name: str = "a.pdf") -> Document:
    now = datetime.now(UTC)
    return Document(
        id=generate_uuidv7(),
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.DRAFT.value,
        idempotency_key=idempotency_key,
        metadata_json={},
        file_name=file_name,
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
        created_at=now,
        updated_at=now,
    )


class _FakeSession:
    def __init__(
        self,
        *,
        commit_error: BaseException | None = None,
        existing: Document | None = None,
    ) -> None:
        self.commit_error = commit_error
        self.existing = existing
        self.added: list[object] = []
        self.refresh_calls = 0
        self.rollback_calls = 0
        self.commit_calls = 0
        self.scalar_calls = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def refresh(self, obj: object) -> None:
        del obj
        self.refresh_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def scalar(self, _stmt: object) -> Document | None:
        self.scalar_calls += 1
        return self.existing


@pytest.mark.asyncio
async def test_create_insert_does_not_refresh() -> None:
    session = _FakeSession()
    service = SqlAlchemyDocumentService(session)  # type: ignore[arg-type]
    tenant_id = generate_uuidv7()
    record, created = await service.create(
        tenant_id=tenant_id,
        created_by="tester",
        correlation_id=generate_uuidv7(),
        idempotency_key="idem-1",
        body=_body(),
    )
    assert created is True
    assert record.tenant_id == tenant_id
    assert session.commit_calls == 1
    assert session.refresh_calls == 0
    assert session.scalar_calls == 0


@pytest.mark.asyncio
async def test_create_unique_replay_same_payload() -> None:
    tenant_id = generate_uuidv7()
    existing = _row(tenant_id=tenant_id, idempotency_key="idem-1")
    session = _FakeSession(
        commit_error=IntegrityError("INSERT", {}, Exception("unique")),
        existing=existing,
    )
    service = SqlAlchemyDocumentService(session)  # type: ignore[arg-type]
    record, created = await service.create(
        tenant_id=tenant_id,
        created_by="tester",
        correlation_id=generate_uuidv7(),
        idempotency_key="idem-1",
        body=_body(),
    )
    assert created is False
    assert record.id == existing.id
    assert session.rollback_calls == 1
    assert session.refresh_calls == 0
    assert session.scalar_calls == 1


@pytest.mark.asyncio
async def test_create_unique_replay_different_payload_is_409() -> None:
    tenant_id = generate_uuidv7()
    existing = _row(tenant_id=tenant_id, idempotency_key="idem-1", file_name="other.pdf")
    session = _FakeSession(
        commit_error=IntegrityError("INSERT", {}, Exception("unique")),
        existing=existing,
    )
    service = SqlAlchemyDocumentService(session)  # type: ignore[arg-type]
    with pytest.raises(ConflictError):
        await service.create(
            tenant_id=tenant_id,
            created_by="tester",
            correlation_id=generate_uuidv7(),
            idempotency_key="idem-1",
            body=_body(),
        )


@pytest.mark.asyncio
async def test_create_integrity_error_without_row_reraises() -> None:
    session = _FakeSession(
        commit_error=IntegrityError("INSERT", {}, Exception("other")),
        existing=None,
    )
    service = SqlAlchemyDocumentService(session)  # type: ignore[arg-type]
    with pytest.raises(IntegrityError):
        await service.create(
            tenant_id=generate_uuidv7(),
            created_by="tester",
            correlation_id=generate_uuidv7(),
            idempotency_key="idem-1",
            body=_body(),
        )
    assert session.rollback_calls == 1
