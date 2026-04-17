"""S3 presigned PUT helpers (ADR-004)."""

from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import boto3
from botocore.client import BaseClient

if TYPE_CHECKING:
    from doc_pipeline.config.settings import Settings

_SSE_HEADER = "x-amz-server-side-encryption"
_SSE_KMS_KEY_HEADER = "x-amz-server-side-encryption-aws-kms-key-id"
_CHECKSUM_HEADER = "x-amz-checksum-sha256"


@dataclass(frozen=True, slots=True)
class PresignResult:
    presigned_url: str
    method: str
    expires_at: datetime
    s3_bucket: str
    s3_key: str
    required_headers: dict[str, str]


def get_s3_client(settings: Settings) -> BaseClient:
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("s3", **kwargs)


def sanitize_filename(file_name: str) -> str:
    base = PurePosixPath(file_name.replace("\\", "/")).name
    if not base or base in {".", ".."}:
        return "upload.bin"
    sanitized = re.sub(r"[^\w.\-]", "_", base)
    return sanitized[:255] or "upload.bin"


def build_object_key(tenant_id: uuid.UUID, document_id: uuid.UUID, file_name: str) -> str:
    return f"{tenant_id}/{document_id}/{sanitize_filename(file_name)}"


def create_presigned_put(
    client: BaseClient,
    *,
    bucket: str,
    key: str,
    content_type: str,
    checksum_sha256: str,
    expires_in: int,
    kms_key_id: str | None = None,
) -> PresignResult:
    """Issue a presigned PUT URL with signed Content-Type and SSE-KMS params.

    Uses boto3 ``generate_presigned_url`` (put_object) so required headers are
    bound into the signature — see AWS SDK docs:
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/generate_presigned_url.html
    """
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=expires_in)
    kms_id = kms_key_id or "alias/doc-pipeline-s3"
    # PutObject ChecksumSHA256 is Base64 of the raw digest, not hex
    # (AWS S3 PutObject / checking object integrity).
    checksum_b64 = base64.b64encode(bytes.fromhex(checksum_sha256)).decode("ascii")

    required_headers: dict[str, str] = {
        "Content-Type": content_type,
        _CHECKSUM_HEADER: checksum_b64,
        _SSE_HEADER: "aws:kms",
        _SSE_KMS_KEY_HEADER: kms_id,
    }

    params: dict[str, str] = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": content_type,
        "ChecksumSHA256": checksum_b64,
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": kms_id,
    }

    presigned_url = client.generate_presigned_url(
        ClientMethod="put_object",
        Params=params,
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )

    return PresignResult(
        presigned_url=presigned_url,
        method="PUT",
        expires_at=expires_at,
        s3_bucket=bucket,
        s3_key=key,
        required_headers=required_headers,
    )
