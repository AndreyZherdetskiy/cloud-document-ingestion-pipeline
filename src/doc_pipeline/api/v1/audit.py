"""Audit timeline — requires document_id (tenant scoped)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from doc_pipeline.api.deps import (
    READ_AUDIT_ROLES,
    Principal,
    get_audit_service,
    get_current_principal,
    require_roles,
)
from doc_pipeline.domain.schemas.audit import AuditEventResponse, AuditListResponse
from doc_pipeline.domain.services.audit_service import AuditRecord, AuditService

router = APIRouter(tags=["audit"])

_PROBLEM_401 = {"description": "Missing or invalid JWT"}
_PROBLEM_403 = {"description": "Authenticated but role not permitted"}
_PROBLEM_404 = {"description": "Document not found in the caller's tenant scope"}
_PROBLEM_422 = {"description": "Request validation failed (document_id required)"}


def _to_response(record: AuditRecord) -> AuditEventResponse:
    return AuditEventResponse(
        id=record.id,
        document_id=record.document_id,
        job_id=record.job_id,
        event_type=record.event_type,
        from_status=record.from_status,
        to_status=record.to_status,
        actor_type=record.actor_type,
        actor_id=record.actor_id,
        correlation_id=record.correlation_id,
        created_at=record.created_at,
    )


@router.get(
    "/audit",
    response_model=AuditListResponse,
    summary="List audit events for a document",
    description=(
        "Requires document_id. Returns append-only audit events for that document "
        "in the caller's tenant. Optional filters: from, to, event_type. "
        "Foreign tenant document IDs return 404."
    ),
    responses={
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        404: _PROBLEM_404,
        422: _PROBLEM_422,
    },
)
async def list_audit(
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[AuditService, Depends(get_audit_service)],
    document_id: Annotated[
        uuid.UUID,
        Query(description="Document UUIDv7 whose audit timeline to return (required)."),
    ],
    from_ts: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive lower bound on created_at (UTC)."),
    ] = None,
    to_ts: Annotated[
        datetime | None,
        Query(alias="to", description="Inclusive upper bound on created_at (UTC)."),
    ] = None,
    event_type: Annotated[
        str | None,
        Query(description="Filter by exact event_type (e.g. JOB_RETRY)."),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor from a previous page's next_cursor."),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Page size (default 50, max 200).", ge=1, le=200),
    ] = 50,
) -> AuditListResponse:
    require_roles(principal, READ_AUDIT_ROLES)
    items, next_cursor = await service.list_for_document(
        tenant_id=principal.tenant_id,
        document_id=document_id,
        from_ts=from_ts,
        to_ts=to_ts,
        event_type=event_type,
        cursor=cursor,
        limit=limit,
    )
    return AuditListResponse(
        items=[_to_response(r) for r in items],
        next_cursor=next_cursor,
        limit=limit,
    )
