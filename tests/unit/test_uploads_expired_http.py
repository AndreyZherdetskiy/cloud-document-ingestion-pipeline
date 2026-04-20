"""Spec §10.3.8 scenario 8 — expired PENDING upload → cancel → re-presign."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import UploadStatus
from doc_pipeline.domain.services.upload_service import (
    InMemoryUploadService,
    expire_stale_upload,
)


@pytest.fixture
def frozen_now() -> datetime:
    return datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)


def expire_upload_fixture(
    upload_service: InMemoryUploadService,
    upload_id: UUID,
    expires_at: datetime,
    *,
    now: datetime,
) -> None:
    """Unit helper: backdate expires_at and apply expire_stale_upload (no live PG)."""
    upload = upload_service.uploads[upload_id]
    upload.expires_at = expires_at
    upload.status = expire_stale_upload(
        expires_at=upload.expires_at,
        current=upload.status,
        now=now,
    )
    assert upload.status is UploadStatus.EXPIRED


@pytest.mark.asyncio
async def test_expired_upload_cancel_and_represign_allowed(
    api_client_tenant_a: AsyncClient,
    draft_document_id: UUID,
    frozen_now: datetime,
    upload_service: InMemoryUploadService,
    moto_s3_bucket: str,
    jwt_settings: Settings,
) -> None:
    """After presign TTL: upload EXPIRED; document CANCELLED or reset; re-presign new upload_id."""
    presign_body = {
        "document_id": str(draft_document_id),
        "content_type": "application/pdf",
        "checksum_sha256": "c" * 64,
    }
    with mock_aws():
        region = jwt_settings.aws_region
        client = boto3.client("s3", region_name=region)
        client.create_bucket(
            Bucket=moto_s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )
        r1 = await api_client_tenant_a.post("/v1/uploads/presign", json=presign_body)
        assert r1.status_code in (200, 201)
        upload_id = UUID(r1.json()["upload_id"])

        expire_upload_fixture(
            upload_service,
            upload_id,
            frozen_now - timedelta(seconds=1),
            now=frozen_now,
        )

        r_cancel = await api_client_tenant_a.post(
            f"/v1/documents/{draft_document_id}/cancel",
        )
        assert r_cancel.status_code in (200, 204)
        doc = (await api_client_tenant_a.get(f"/v1/documents/{draft_document_id}")).json()
        # CANCELLED = hard cancel; DRAFT/UPLOADING = re-presign-ready reset after expiry
        assert doc["status"] in ("CANCELLED", "UPLOADING", "DRAFT")

        r2 = await api_client_tenant_a.post("/v1/uploads/presign", json=presign_body)
        assert r2.status_code in (200, 201)
        assert r2.json()["presigned_url"]
        assert r2.json()["upload_id"] != str(upload_id)
