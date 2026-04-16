"""Pydantic schemas for presigned upload URLs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PresignRequest(BaseModel):
    document_id: uuid.UUID = Field(
        description="Target document UUIDv7 (must be DRAFT in the caller tenant).",
    )
    content_type: str = Field(
        description=(
            "MIME type the client will send on the S3 PUT (e.g. application/pdf). "
            "Must be in the tenant allowlist."
        ),
    )
    checksum_sha256: str = Field(
        description=(
            "SHA-256 hex digest (64 chars) of the object bytes. Stored on the document; "
            "the S3 PUT header x-amz-checksum-sha256 is the Base64 form of this digest."
        ),
        min_length=64,
        max_length=64,
    )


class PresignResponse(BaseModel):
    upload_id: uuid.UUID = Field(
        description="Upload UUIDv7 row id (PENDING until S3 PUT completes).",
    )
    presigned_url: str = Field(
        description="Time-limited S3 PUT URL — never logged server-side; client uploads directly.",
    )
    method: str = Field(description="HTTP method for the upload (always PUT).")
    expires_at: datetime = Field(description="UTC expiry of the presigned URL.")
    s3_bucket: str = Field(description="Destination S3 bucket name.")
    s3_key: str = Field(description="Object key: {tenant_id}/{document_id}/{sanitized_filename}.")
    required_headers: dict[str, str] = Field(
        description=(
            "Headers the client must include on PUT: Content-Type, checksum, SSE-KMS keys."
        ),
    )
