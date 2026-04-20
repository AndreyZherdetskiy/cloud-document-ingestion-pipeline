"""Documents create / list / get / cancel — control plane only (no file bytes)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, Query, Response

from doc_pipeline.api.deps import (
    CANCEL_DOCUMENT_ROLES,
    CREATE_DOCUMENT_ROLES,
    READ_DOCUMENT_ROLES,
    Principal,
    enforce_rate_limit,
    get_audit_service,
    get_current_principal,
    get_document_service,
    get_job_service,
    get_redis,
    get_settings_dep,
    get_upload_service,
    require_roles,
)
from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.schemas.documents import (
    AuditEventBrief,
    DocumentCreate,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    JobSummary,
)
from doc_pipeline.domain.services.audit_service import AuditService
from doc_pipeline.domain.services.document_service import DocumentRecord, DocumentService
from doc_pipeline.domain.services.job_service import JobService
from doc_pipeline.domain.services.upload_service import UploadService
from doc_pipeline.infrastructure.cache.redis import RedisCache
from doc_pipeline.logging import get_correlation_id

router = APIRouter(tags=["documents"])

_IDEMPOTENCY_HEADER_DESCRIPTION = (
    "Client idempotency key (required). Same key with matching payload returns 200 "
    "and the existing document; same key with a different payload returns 409."
)

_CREATE_EXAMPLES = {
    "invoice": {
        "summary": "Create invoice metadata",
        "description": "Metadata only — upload the PDF via POST /v1/uploads/presign.",
        "value": {
            "document_type": "INVOICE",
            "external_ref": "inv-001",
            "file_name": "invoice.pdf",
            "content_type": "application/pdf",
            "checksum_sha256": "a" * 64,
        },
    },
}

_PROBLEM_401 = {"description": "Missing or invalid JWT"}
_PROBLEM_403 = {"description": "Authenticated but role not permitted"}
_PROBLEM_404 = {"description": "Document not found in the caller's tenant scope"}
_PROBLEM_409 = {
    "description": "Idempotency-Key reused with a different payload or invalid transition",
}
_PROBLEM_422 = {"description": "Request validation failed"}
_PROBLEM_429 = {"description": "Rate limit exceeded"}


def _to_response(record: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        status=record.status,
        document_type=record.document_type,
        external_ref=record.external_ref,
        title=record.title,
        file_name=record.file_name,
        content_type=record.mime_type,
        created_at=record.created_at,
        correlation_id=record.correlation_id,
    )


def _correlation_uuid() -> uuid.UUID:
    raw = get_correlation_id()
    if raw:
        return uuid.UUID(raw)
    return generate_uuidv7()


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=201,
    summary="Create document metadata",
    description=(
        "Creates a DRAFT document record for the caller's tenant. "
        "Files never stream through this API — obtain a presigned PUT URL next. "
        "Requires Idempotency-Key. ROLE_API_CLIENT (and admin) may create."
    ),
    responses={
        200: {"description": "Idempotent replay — same document returned"},
        201: {"description": "Document created in DRAFT"},
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        409: _PROBLEM_409,
        422: _PROBLEM_422,
        429: _PROBLEM_429,
    },
)
async def create_document(
    response: Response,
    body: Annotated[DocumentCreate, Body(openapi_examples=_CREATE_EXAMPLES)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    redis: Annotated[RedisCache, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            description=_IDEMPOTENCY_HEADER_DESCRIPTION,
        ),
    ],
) -> DocumentResponse:
    require_roles(principal, CREATE_DOCUMENT_ROLES)
    await enforce_rate_limit(principal, redis, settings)
    record, created = await service.create(
        tenant_id=principal.tenant_id,
        created_by=principal.sub,
        correlation_id=_correlation_uuid(),
        idempotency_key=idempotency_key,
        body=body,
    )
    response.status_code = 201 if created else 200
    return _to_response(record)


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List documents",
    description=(
        "Lists documents for the caller's tenant with optional filters. "
        "Cursor pagination only (default limit 50, max 200). No offset."
    ),
    responses={
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        422: _PROBLEM_422,
    },
)
async def list_documents(
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    status: Annotated[
        DocumentStatus | None,
        Query(description="Filter by document status."),
    ] = None,
    document_type: Annotated[
        DocumentType | None,
        Query(description="Filter by document type."),
    ] = None,
    external_ref: Annotated[
        str | None,
        Query(description="Filter by exact external_ref."),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor from a previous page's next_cursor."),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Page size (default 50, max 200).", ge=1, le=200),
    ] = 50,
) -> DocumentListResponse:
    require_roles(principal, READ_DOCUMENT_ROLES)
    items, next_cursor = await service.list(
        tenant_id=principal.tenant_id,
        status=status,
        document_type=document_type,
        external_ref=external_ref,
        cursor=cursor,
        limit=limit,
    )
    return DocumentListResponse(
        items=[_to_response(r) for r in items],
        next_cursor=next_cursor,
        limit=limit,
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get document",
    description=(
        "Returns document metadata, latest job summary, and up to five recent audit events. "
        "Foreign tenant IDs return 404 (not 403)."
    ),
    responses={
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        404: _PROBLEM_404,
        422: _PROBLEM_422,
    },
)
async def get_document(
    document_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    jobs: Annotated[JobService, Depends(get_job_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> DocumentDetailResponse:
    require_roles(principal, READ_DOCUMENT_ROLES)
    record = await service.get(tenant_id=principal.tenant_id, document_id=document_id)
    base = _to_response(record)
    latest = await jobs.latest_for_document(
        tenant_id=principal.tenant_id,
        document_id=document_id,
    )
    job_summary = (
        JobSummary(
            id=latest.id,
            status=latest.status.value,
            job_type=latest.job_type.value,
        )
        if latest is not None
        else JobSummary()
    )
    recent = await audit.recent_for_document(
        tenant_id=principal.tenant_id,
        document_id=document_id,
        limit=5,
    )
    return DocumentDetailResponse(
        **base.model_dump(),
        job=job_summary,
        recent_audit=[
            AuditEventBrief(
                id=e.id,
                event_type=e.event_type,
                from_status=e.from_status,
                to_status=e.to_status,
                created_at=e.created_at,
            )
            for e in recent
        ],
    )


@router.post(
    "/documents/{document_id}/cancel",
    response_model=DocumentResponse,
    summary="Cancel document or reset expired upload",
    description=(
        "Cancels a non-terminal document via the status state machine (to CANCELLED). "
        "If the document is UPLOADING and its upload TTL has expired, resets to DRAFT "
        "so the client can re-presign."
    ),
    responses={
        200: {"description": "Document cancelled or reset for re-presign"},
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        404: _PROBLEM_404,
        409: _PROBLEM_409,
        422: _PROBLEM_422,
    },
)
async def cancel_document(
    document_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> DocumentResponse:
    require_roles(principal, CANCEL_DOCUMENT_ROLES)
    reset = await uploads.has_expired_upload(document_id=document_id)
    record = await service.cancel(
        tenant_id=principal.tenant_id,
        document_id=document_id,
        reset_for_represign=reset,
    )
    return _to_response(record)
