"""Shared seed helpers — tenant/document upsert + S3 put + optional SQS check."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from botocore.client import BaseClient
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.infrastructure.aws.s3 import build_object_key


def print_jwt_bootstrap_note(settings: Settings) -> None:
    """Point operators at Settings/.env — never print PEM or private material."""
    print(
        "JWT bootstrap: configure JWT_PUBLIC_KEY_PEM / JWT_ISSUER / JWT_AUDIENCE "
        f"via Settings (.env). issuer={settings.jwt_issuer!r} "
        f"audience={settings.jwt_audience!r}. Do not commit private keys."
    )


async def ensure_tenant(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
) -> tuple[Tenant, bool]:
    existing = await session.scalar(select(Tenant).where(Tenant.slug == slug))
    if existing is not None:
        return existing, False
    tenant = Tenant(id=generate_uuidv7(), name=name, slug=slug, config_json={})
    session.add(tenant)
    return tenant, True


async def ensure_document(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    idempotency_key: str,
    document_type: DocumentType,
    status: DocumentStatus,
    file_name: str,
    mime_type: str,
    s3_bucket: str,
    metadata_json: dict[str, object] | None = None,
    failure_reason: str | None = None,
    title: str | None = None,
) -> tuple[Document, bool]:
    existing = await session.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, False

    doc_id = generate_uuidv7()
    s3_key = build_object_key(tenant_id, doc_id, file_name)
    doc = Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=document_type.value,
        status=status.value,
        idempotency_key=idempotency_key,
        title=title or file_name,
        metadata_json=metadata_json or {},
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_name=file_name,
        file_size_bytes=64,
        mime_type=mime_type,
        checksum_sha256="a" * 64,
        failure_reason=failure_reason,
        created_by="seed",
    )
    session.add(doc)
    return doc, True


def ensure_s3_object(
    s3: BaseClient,
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
) -> bool:
    """Put object if missing. Returns True when a new object was written."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return False
    except ClientError:
        pass
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    return True


def ensure_bucket(s3: BaseClient, bucket: str, region: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)


def check_queues(sqs: BaseClient | None, settings: Settings) -> bool:
    """Return True when all four queues exist, or when no SQS client was injected (skip)."""
    if sqs is None:
        return True
    for url in (
        settings.sqs_queue_url,
        settings.sqs_dlq_url,
        settings.sqs_processing_queue_url,
        settings.sqs_processing_dlq_url,
    ):
        try:
            sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])
        except ClientError:
            return False
    return True


def fixture_body(label: str) -> bytes:
    return f"seed-fixture:{label}\n".encode()
