"""Presigned S3 upload URLs — files never stream through the API (ADR-004)."""

from __future__ import annotations

from typing import Annotated

import structlog
from botocore.client import BaseClient
from fastapi import APIRouter, Body, Depends

from doc_pipeline.api.deps import (
    CREATE_DOCUMENT_ROLES,
    Principal,
    enforce_rate_limit,
    get_current_principal,
    get_redis,
    get_s3_client,
    get_settings_dep,
    get_upload_service,
    require_roles,
)
from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.schemas.uploads import PresignRequest, PresignResponse
from doc_pipeline.domain.services.upload_service import UploadService
from doc_pipeline.infrastructure.cache.redis import RedisCache

router = APIRouter(tags=["uploads"])
logger = structlog.get_logger(__name__)

_PRESIGN_EXAMPLES = {
    "pdf_upload": {
        "summary": "Presign PDF upload",
        "description": (
            "After creating document metadata, request a presigned PUT URL. "
            "Upload the file directly to S3 with required_headers."
        ),
        "value": {
            "document_id": "01900000-0000-7000-8000-000000000001",
            "content_type": "application/pdf",
            "checksum_sha256": "a" * 64,
        },
    },
}

_PROBLEM_400 = {"description": "Business validation failed (e.g. MIME not in tenant allowlist)"}
_PROBLEM_401 = {"description": "Missing or invalid JWT"}
_PROBLEM_403 = {"description": "Authenticated but role not permitted"}
_PROBLEM_404 = {"description": "Document not found in the caller's tenant scope"}
_PROBLEM_422 = {"description": "Request validation failed"}
_PROBLEM_429 = {"description": "Rate limit exceeded"}


@router.post(
    "/uploads/presign",
    response_model=PresignResponse,
    summary="Issue presigned S3 PUT URL",
    description=(
        "Returns a time-limited presigned PUT URL for direct client upload to S3. "
        "On success the document transitions DRAFT → UPLOADING and an uploads row is "
        "created with PENDING status. MIME type is checked against the tenant allowlist "
        "before any URL is issued. Default TTL is 15 minutes (tenant cap 60 minutes)."
    ),
    responses={
        200: {"description": "Presigned URL issued"},
        400: _PROBLEM_400,
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        404: _PROBLEM_404,
        422: _PROBLEM_422,
        429: _PROBLEM_429,
    },
)
async def presign_upload(
    body: Annotated[PresignRequest, Body(openapi_examples=_PRESIGN_EXAMPLES)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    upload_service: Annotated[UploadService, Depends(get_upload_service)],
    s3_client: Annotated[BaseClient, Depends(get_s3_client)],
    redis: Annotated[RedisCache, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> PresignResponse:
    require_roles(principal, CREATE_DOCUMENT_ROLES)
    await enforce_rate_limit(principal, redis, settings)
    result = await upload_service.presign(
        tenant_id=principal.tenant_id,
        body=body,
        s3_client=s3_client,
        settings=settings,
    )
    logger.info(
        "presign issued",
        upload_id=str(result.upload_id),
        document_id=str(body.document_id),
        s3_bucket=result.s3_bucket,
        s3_key=result.s3_key,
        method=result.method,
    )
    return result
