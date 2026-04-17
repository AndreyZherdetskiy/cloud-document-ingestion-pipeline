"""Presign S3 helper (moto) and upload service unit tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import UploadStatus
from doc_pipeline.domain.services.upload_service import expire_stale_upload
from doc_pipeline.infrastructure.aws.s3 import build_object_key, create_presigned_put

TENANT_ID = UUID("01900000-0000-7000-8000-0000000000aa")
DOCUMENT_ID = UUID("01900000-0000-7000-8000-000000000001")
CHECKSUM = "b" * 64
PRESIGN_BODY = {
    "document_id": str(DOCUMENT_ID),
    "content_type": "application/pdf",
    "checksum_sha256": CHECKSUM,
}


@mock_aws
def test_presign_shape_and_key_layout() -> None:
    bucket = "dev-doc-pipeline"
    region = "eu-central-1"
    client = boto3.client("s3", region_name=region)
    client.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": region},
    )
    key = build_object_key(TENANT_ID, DOCUMENT_ID, "invoice.pdf")
    assert key == f"{TENANT_ID}/{DOCUMENT_ID}/invoice.pdf"
    result = create_presigned_put(
        client,
        bucket=bucket,
        key=key,
        content_type="application/pdf",
        checksum_sha256=CHECKSUM,
        expires_in=900,
    )
    assert result.method == "PUT"
    assert bucket in result.presigned_url
    assert "Content-Type" in result.required_headers
    assert result.required_headers["x-amz-checksum-sha256"] == base64.b64encode(
        bytes.fromhex(CHECKSUM)
    ).decode("ascii")
    assert result.expires_at <= datetime.now(UTC) + timedelta(seconds=901)


def test_build_object_key_sanitizes_path_traversal() -> None:
    key = build_object_key(TENANT_ID, DOCUMENT_ID, "../../etc/passwd")
    assert key == f"{TENANT_ID}/{DOCUMENT_ID}/passwd"
    assert ".." not in key.split("/")[-1]


def test_expired_upload_marks_expired(frozen_now: datetime) -> None:
    status = expire_stale_upload(
        expires_at=frozen_now - timedelta(seconds=1),
        current=UploadStatus.PENDING,
        now=frozen_now,
    )
    assert status is UploadStatus.EXPIRED


def test_non_expired_upload_stays_pending(frozen_now: datetime) -> None:
    status = expire_stale_upload(
        expires_at=frozen_now + timedelta(minutes=5),
        current=UploadStatus.PENDING,
        now=frozen_now,
    )
    assert status is UploadStatus.PENDING


@pytest.fixture
def frozen_now() -> datetime:
    return datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_presign_api_success(
    api_client_tenant_a: AsyncClient,
    draft_document_id: UUID,
    moto_s3_bucket: str,
    jwt_settings: Settings,
) -> None:
    import boto3

    with mock_aws():
        region = jwt_settings.aws_region
        client = boto3.client("s3", region_name=region)
        client.create_bucket(
            Bucket=moto_s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )
        body = {
            "document_id": str(draft_document_id),
            "content_type": "application/pdf",
            "checksum_sha256": "c" * 64,
        }
        r = await api_client_tenant_a.post("/v1/uploads/presign", json=body)
    assert r.status_code == 200
    payload = r.json()
    assert payload["method"] == "PUT"
    assert payload["upload_id"]
    assert moto_s3_bucket in payload["presigned_url"]
    assert payload["s3_bucket"] == moto_s3_bucket
    assert payload["required_headers"]["Content-Type"] == "application/pdf"
    assert "x-amz-checksum-sha256" in payload["required_headers"]
    assert "x-amz-server-side-encryption" in payload["required_headers"]
    expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
    assert expires_at <= datetime.now(UTC) + timedelta(seconds=901)


@pytest.mark.asyncio
async def test_presign_mime_not_allowed_returns_400_before_url(
    api_client_tenant_a: AsyncClient,
    draft_document_id: UUID,
) -> None:
    body = {
        "document_id": str(draft_document_id),
        "content_type": "application/x-msdownload",
        "checksum_sha256": "d" * 64,
    }
    r = await api_client_tenant_a.post("/v1/uploads/presign", json=body)
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "presigned_url" not in r.text


@pytest.mark.asyncio
async def test_presign_transitions_document_to_uploading(
    api_client_tenant_a: AsyncClient,
    draft_document_id: UUID,
    moto_s3_bucket: str,
    jwt_settings: Settings,
) -> None:
    import boto3

    with mock_aws():
        region = jwt_settings.aws_region
        client = boto3.client("s3", region_name=region)
        client.create_bucket(
            Bucket=moto_s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )
        body = {
            "document_id": str(draft_document_id),
            "content_type": "application/pdf",
            "checksum_sha256": "e" * 64,
        }
        r = await api_client_tenant_a.post("/v1/uploads/presign", json=body)
        assert r.status_code == 200

        detail = await api_client_tenant_a.get(f"/v1/documents/{draft_document_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "UPLOADING"
