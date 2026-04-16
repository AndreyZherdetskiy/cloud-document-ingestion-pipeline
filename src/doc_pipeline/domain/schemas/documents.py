"""Pydantic schemas for document create/list/get."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from doc_pipeline.domain.enums import DocumentStatus, DocumentType


class DocumentCreate(BaseModel):
    document_type: DocumentType = Field(
        description="Logical document type (INVOICE, KYC, CONTRACT).",
    )
    external_ref: str | None = Field(
        default=None,
        description="Caller-side reference (invoice number, case id). Optional.",
    )
    title: str | None = Field(default=None, description="Human-readable document title.")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque caller metadata stored with the document.",
    )
    file_name: str | None = Field(
        default=None,
        description="Original file name declared by the client.",
    )
    content_type: str | None = Field(
        default=None,
        description=(
            "Declared MIME type (e.g. application/pdf). "
            "Files are uploaded via presign, not this API."
        ),
    )
    declared_size_bytes: int | None = Field(
        default=None,
        description="Declared object size in bytes (optional; enforced later via S3).",
        ge=0,
    )
    checksum_sha256: str | None = Field(
        default=None,
        description="Optional SHA-256 hex digest (64 chars) declared at create time.",
        min_length=64,
        max_length=64,
    )


class DocumentResponse(BaseModel):
    id: uuid.UUID = Field(description="Document UUIDv7 primary key.")
    tenant_id: uuid.UUID = Field(description="Owning tenant UUIDv7 from the JWT.")
    status: DocumentStatus = Field(description="Current document lifecycle status.")
    document_type: DocumentType = Field(description="Logical document type.")
    external_ref: str | None = Field(default=None, description="Caller-side reference.")
    title: str | None = Field(default=None, description="Human-readable title.")
    file_name: str | None = Field(default=None, description="Declared file name.")
    content_type: str | None = Field(default=None, description="Declared MIME type.")
    created_at: datetime = Field(description="Creation timestamp (UTC).")
    correlation_id: uuid.UUID = Field(description="Correlation UUIDv7 bound to this create.")


class JobSummary(BaseModel):
    id: uuid.UUID | None = Field(default=None, description="Latest job id when present.")
    status: str | None = Field(default=None, description="Latest job status when present.")
    job_type: str | None = Field(default=None, description="Latest job type when present.")


class AuditEventBrief(BaseModel):
    id: uuid.UUID = Field(description="Audit event UUIDv7.")
    event_type: str = Field(description="Audit event type.")
    from_status: str | None = Field(default=None, description="Previous status if a transition.")
    to_status: str | None = Field(default=None, description="New status if a transition.")
    created_at: datetime = Field(description="When the audit event was recorded.")


class DocumentDetailResponse(DocumentResponse):
    job: JobSummary = Field(
        default_factory=JobSummary,
        description="Latest job summary for this document (empty when none).",
    )
    recent_audit: list[AuditEventBrief] = Field(
        default_factory=list,
        description="Up to five most recent audit events.",
    )


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse] = Field(description="Page of documents for the caller tenant.")
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next page; null when no more items.",
    )
    limit: int = Field(description="Page size applied to this response.")
