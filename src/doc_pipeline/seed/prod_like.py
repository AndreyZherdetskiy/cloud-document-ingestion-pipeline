"""Prod-like seed — several tenants, type mix, virus-fail + invalid-MIME fixtures."""

from __future__ import annotations

from botocore.client import BaseClient
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.models.tenant import Tenant
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

_TENANTS: tuple[tuple[str, str], ...] = (
    ("acme", "Acme Corp"),
    ("globex", "Globex Industries"),
    ("initech", "Initech LLC"),
)

# (tenant_slug, idem_key, type, file_name, mime, status, fixture_tag, failure_reason)
_DOCS: tuple[
    tuple[str, str, DocumentType, str, str, DocumentStatus, str | None, str | None],
    ...,
] = (
    (
        "acme",
        "pl-acme-invoice-1",
        DocumentType.INVOICE,
        "acme-invoice.pdf",
        "application/pdf",
        DocumentStatus.PROCESSED,
        None,
        None,
    ),
    (
        "acme",
        "pl-acme-kyc-1",
        DocumentType.KYC,
        "acme-kyc.pdf",
        "application/pdf",
        DocumentStatus.UPLOADED,
        None,
        None,
    ),
    (
        "globex",
        "pl-globex-contract-1",
        DocumentType.CONTRACT,
        "globex-contract.pdf",
        "application/pdf",
        DocumentStatus.PROCESSED,
        None,
        None,
    ),
    (
        "globex",
        "pl-globex-invoice-1",
        DocumentType.INVOICE,
        "globex-invoice.pdf",
        "application/pdf",
        DocumentStatus.QUEUED,
        None,
        None,
    ),
    (
        "initech",
        "pl-initech-kyc-1",
        DocumentType.KYC,
        "initech-kyc.png",
        "image/png",
        DocumentStatus.UPLOADED,
        None,
        None,
    ),
    (
        "initech",
        "pl-initech-virus-fail",
        DocumentType.INVOICE,
        "eicar-stub.pdf",
        "application/pdf",
        DocumentStatus.FAILED,
        "virus_stub_fail",
        "virus_detected",
    ),
    (
        "initech",
        "pl-initech-invalid-mime",
        DocumentType.CONTRACT,
        "payload.exe",
        "application/x-msdownload",
        DocumentStatus.FAILED,
        "invalid_mime",
        "invalid_mime",
    ),
)


async def seed_prod_like(
    session: AsyncSession,
    s3: BaseClient,
    settings: Settings,
    *,
    sqs: BaseClient | None = None,
) -> SeedReport:
    print_jwt_bootstrap_note(settings)
    ensure_bucket(s3, settings.s3_bucket, settings.aws_region)

    tenants_created = 0
    documents_created = 0
    s3_objects_created = 0
    tenants: dict[str, Tenant] = {}

    for slug, name in _TENANTS:
        tenant, created = await ensure_tenant(session, slug=slug, name=name)
        tenants[slug] = tenant
        if created:
            tenants_created += 1

    for (
        slug,
        idem_key,
        doc_type,
        file_name,
        mime,
        status,
        fixture_tag,
        failure_reason,
    ) in _DOCS:
        tenant = tenants[slug]
        meta: dict[str, object] = (
            {"fixture": fixture_tag} if fixture_tag else {"fixture": "prod_like"}
        )
        doc, created = await ensure_document(
            session,
            tenant_id=tenant.id,
            idempotency_key=idem_key,
            document_type=doc_type,
            status=status,
            file_name=file_name,
            mime_type=mime,
            s3_bucket=settings.s3_bucket,
            metadata_json=meta,
            failure_reason=failure_reason,
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
        tenants_created=tenants_created,
        documents_created=documents_created,
        s3_objects_created=s3_objects_created,
        queues_ok=queues_ok,
    )
