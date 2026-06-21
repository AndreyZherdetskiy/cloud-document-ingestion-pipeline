"""In-memory worker session fakes and S3 ingest event builders for unit tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.models.audit_log import AuditLog
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant


class _ScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


class FakeWorkerSession:
    """In-memory async session: MagicMock-style add; awaitables for commit/get/scalars."""

    def __init__(self, document: Document, tenant: Tenant | None = None) -> None:
        self.document = document
        self.tenant = tenant
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def get(self, model: type, pk: UUID) -> Any | None:
        if model is Document and pk == self.document.id:
            return self.document
        if model is Tenant and self.tenant is not None and pk == self.tenant.id:
            return self.tenant
        return None

    async def scalar(self, stmt: object) -> Any | None:
        text = str(stmt).lower()
        if "from tenants" in text or "tenants" in text and "documents" not in text:
            return self.tenant
        if "from documents" in text or "documents" in text:
            return self.document
        return None

    async def scalars(self, stmt: object) -> _ScalarResult:
        rows = [o for o in self.added if isinstance(o, AuditLog)]
        compiled = str(stmt)
        rows = [r for r in rows if r.document_id == self.document.id]
        if "FAILED" in compiled:
            rows = [r for r in rows if r.to_status == DocumentStatus.FAILED.value]
        if "PROCESSED" in compiled:
            rows = [r for r in rows if r.to_status == DocumentStatus.PROCESSED.value]
        return _ScalarResult(rows)


def event_for(document: Document) -> dict[str, str]:
    """Build the logical S3 ingest event the worker parses (not raw SNS wrapping)."""
    return {
        "schema_version": "1",
        "event_source": "aws:s3",
        "event_name": "ObjectCreated:Put",
        "bucket": document.s3_bucket or "dev-doc-pipeline",
        "object_key": document.s3_key or f"{document.tenant_id}/{document.id}/invoice.pdf",
        "etag": "abc",
        "tenant_id": str(document.tenant_id),
        "document_id": str(document.id),
    }
