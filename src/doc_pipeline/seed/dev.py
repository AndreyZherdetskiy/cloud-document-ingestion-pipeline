"""Dev seed — tenant acme, 1–3 S3 objects, optional SQS existence check."""

from __future__ import annotations

from botocore.client import BaseClient
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.seed.common import (
    check_queues,
    ensure_bucket,
    ensure_document,
    ensure_s3_object,
    ensure_tenant,
    fixture_body,
    print_jwt_bootstrap_note,
)
from doc_pipeline.seed.report import SeedReport

_DEV_DOCS: tuple[tuple[str, DocumentType, str, str], ...] = (
    ("seed-dev-invoice-1", DocumentType.INVOICE, "invoice-1.pdf", "application/pdf"),
    ("seed-dev-kyc-1", DocumentType.KYC, "kyc-1.pdf", "application/pdf"),
    ("seed-dev-contract-1", DocumentType.CONTRACT, "contract-1.pdf", "application/pdf"),
)


async def seed_dev(
    session: AsyncSession,
    s3: BaseClient,
    settings: Settings,
    *,
    sqs: BaseClient | None = None,
) -> SeedReport:
    print_jwt_bootstrap_note(settings)
    ensure_bucket(s3, settings.s3_bucket, settings.aws_region)

    tenant, tenant_created = await ensure_tenant(session, slug="acme", name="Acme Corp")
    documents_created = 0
    s3_objects_created = 0

    for idem_key, doc_type, file_name, mime in _DEV_DOCS:
        doc, created = await ensure_document(
            session,
            tenant_id=tenant.id,
            idempotency_key=idem_key,
            document_type=doc_type,
            status=DocumentStatus.UPLOADED,
            file_name=file_name,
            mime_type=mime,
            s3_bucket=settings.s3_bucket,
            metadata_json={"fixture": "dev"},
        )
        if created:
            documents_created += 1
        assert doc.s3_key is not None
        if ensure_s3_object(
            s3,
            bucket=settings.s3_bucket,
            key=doc.s3_key,
            body=fixture_body(idem_key),
            content_type=mime,
        ):
            s3_objects_created += 1

    await session.commit()
    queues_ok = check_queues(sqs, settings)
    return SeedReport(
        tenant_slug="acme",
        tenants_created=1 if tenant_created else 0,
        documents_created=documents_created,
        s3_objects_created=s3_objects_created,
        queues_ok=queues_ok,
    )
