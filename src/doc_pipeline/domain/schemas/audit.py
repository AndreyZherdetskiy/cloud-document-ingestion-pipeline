"""Pydantic schemas for audit timeline."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from doc_pipeline.domain.enums import ActorType


class AuditEventResponse(BaseModel):
    id: uuid.UUID = Field(description="Audit event UUIDv7.")
    document_id: uuid.UUID = Field(description="Document this event belongs to.")
    job_id: uuid.UUID | None = Field(default=None, description="Related job when applicable.")
    event_type: str = Field(description="Audit event type (e.g. JOB_RETRY, DOCUMENT_CREATED).")
    from_status: str | None = Field(default=None, description="Previous status if a transition.")
    to_status: str | None = Field(default=None, description="New status if a transition.")
    actor_type: ActorType = Field(description="Actor category (USER, SYSTEM, OPERATOR).")
    actor_id: str | None = Field(default=None, description="Actor subject id when known.")
    correlation_id: uuid.UUID = Field(description="Correlation UUIDv7 for the request chain.")
    created_at: datetime = Field(description="When the audit event was recorded (UTC).")


class AuditListResponse(BaseModel):
    items: list[AuditEventResponse] = Field(description="Audit events newest-first.")
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next page; null when no more items.",
    )
    limit: int = Field(description="Page size applied to this response.")
