"""Jobs get/list/retry/cancel."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.api.deps import (
    CANCEL_JOB_ROLES,
    READ_JOB_ROLES,
    RETRY_JOB_ROLES,
    Principal,
    get_audit_service,
    get_current_principal,
    get_db_session,
    get_job_service,
    require_roles,
)
from doc_pipeline.domain.enums import ActorType, JobStatus
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.schemas.jobs import JobListResponse, JobResponse
from doc_pipeline.domain.services.audit_service import AuditRecord, AuditService
from doc_pipeline.domain.services.job_service import JobRecord, JobService
from doc_pipeline.logging import get_correlation_id

router = APIRouter(tags=["jobs"])

_PROBLEM_401 = {"description": "Missing or invalid JWT"}
_PROBLEM_403 = {"description": "Authenticated but role not permitted"}
_PROBLEM_404 = {"description": "Job not found in the caller's tenant scope"}
_PROBLEM_409 = {"description": "Invalid job status transition"}
_PROBLEM_422 = {"description": "Request validation failed"}


def _to_response(record: JobRecord) -> JobResponse:
    return JobResponse(
        id=record.id,
        document_id=record.document_id,
        job_type=record.job_type,
        status=record.status,
        attempt=record.attempt,
        max_attempts=record.max_attempts,
        error_code=record.error_code,
        error_message=record.error_message,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _correlation_uuid() -> uuid.UUID:
    raw = get_correlation_id()
    if raw:
        return uuid.UUID(raw)
    return generate_uuidv7()


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="List jobs",
    description=(
        "Lists processing jobs for the caller's tenant. "
        "Filters: status, document_id, older_than (e.g. 30m). Cursor pagination."
    ),
    responses={
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        422: _PROBLEM_422,
    },
)
async def list_jobs(
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[JobService, Depends(get_job_service)],
    status: Annotated[
        JobStatus | None,
        Query(description="Filter by job status."),
    ] = None,
    document_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by parent document id."),
    ] = None,
    older_than: Annotated[
        str | None,
        Query(description="Only jobs created at or before now−duration (e.g. 30m, 2h)."),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor from a previous page's next_cursor."),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Page size (default 50, max 200).", ge=1, le=200),
    ] = 50,
) -> JobListResponse:
    require_roles(principal, READ_JOB_ROLES)
    items, next_cursor = await service.list(
        tenant_id=principal.tenant_id,
        status=status,
        document_id=document_id,
        older_than=older_than,
        cursor=cursor,
        limit=limit,
    )
    return JobListResponse(
        items=[_to_response(r) for r in items],
        next_cursor=next_cursor,
        limit=limit,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get job",
    description="Returns a single job by id. Foreign tenant IDs return 404 (not 403).",
    responses={
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        404: _PROBLEM_404,
        422: _PROBLEM_422,
    },
)
async def get_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[JobService, Depends(get_job_service)],
) -> JobResponse:
    require_roles(principal, READ_JOB_ROLES)
    record = await service.get(tenant_id=principal.tenant_id, job_id=job_id)
    return _to_response(record)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobResponse,
    summary="Retry failed or stuck job",
    description=(
        "Operator only. Retries a job in FAILED or STUCK status: status → PENDING, "
        "attempt incremented. Other statuses return 409. Writes audit event JOB_RETRY."
    ),
    responses={
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        404: _PROBLEM_404,
        409: _PROBLEM_409,
        422: _PROBLEM_422,
    },
)
async def retry_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[JobService, Depends(get_job_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobResponse:
    require_roles(principal, RETRY_JOB_ROLES)
    before = await service.get(tenant_id=principal.tenant_id, job_id=job_id)
    record = await service.retry(tenant_id=principal.tenant_id, job_id=job_id)
    await audit.append(
        AuditRecord(
            id=generate_uuidv7(),
            tenant_id=principal.tenant_id,
            document_id=record.document_id,
            job_id=record.id,
            event_type="JOB_RETRY",
            from_status=before.status.value,
            to_status=record.status.value,
            actor_type=ActorType.OPERATOR,
            actor_id=principal.sub,
            correlation_id=_correlation_uuid(),
        )
    )
    # Status + audit in one transaction (ADR-003); InMemory path no-ops commit.
    await session.commit()
    return _to_response(record)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobResponse,
    summary="Cancel job",
    description=(
        "Operator or Admin. Cancels a non-terminal job (PENDING/RUNNING/FAILED/STUCK). "
        "SUCCEEDED or already CANCELLED returns 409."
    ),
    responses={
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        404: _PROBLEM_404,
        409: _PROBLEM_409,
        422: _PROBLEM_422,
    },
)
async def cancel_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[JobService, Depends(get_job_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobResponse:
    require_roles(principal, CANCEL_JOB_ROLES)
    before = await service.get(tenant_id=principal.tenant_id, job_id=job_id)
    record = await service.cancel(tenant_id=principal.tenant_id, job_id=job_id)
    await audit.append(
        AuditRecord(
            id=generate_uuidv7(),
            tenant_id=principal.tenant_id,
            document_id=record.document_id,
            job_id=record.id,
            event_type="JOB_CANCEL",
            from_status=before.status.value,
            to_status=record.status.value,
            actor_type=ActorType.OPERATOR,
            actor_id=principal.sub,
            correlation_id=_correlation_uuid(),
        )
    )
    # Status + audit in one transaction (ADR-003); InMemory path no-ops commit.
    await session.commit()
    return _to_response(record)
