"""Presign orchestration — MIME allowlist, DRAFT→UPLOADING, upload rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from botocore.client import BaseClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType, UploadStatus
from doc_pipeline.domain.errors import NotFoundError, ValidationError
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.domain.models.upload import Upload
from doc_pipeline.domain.schemas.uploads import PresignRequest, PresignResponse
from doc_pipeline.domain.services.document_service import DocumentRecord, DocumentService
from doc_pipeline.domain.state_machine import transition
from doc_pipeline.infrastructure.aws.s3 import PresignResult, build_object_key, create_presigned_put

DEFAULT_ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)
DEFAULT_PRESIGN_TTL_SECONDS = 900
MAX_PRESIGN_TTL_SECONDS = 3600


def allowed_mime_types_for_tenant(config_json: dict[str, Any]) -> frozenset[str]:
    raw = config_json.get("allowed_mime_types")
    if isinstance(raw, list) and raw:
        return frozenset(str(item) for item in raw)
    return DEFAULT_ALLOWED_MIME_TYPES


def presign_ttl_seconds_for_tenant(config_json: dict[str, Any]) -> int:
    raw = config_json.get("presign_ttl_seconds", DEFAULT_PRESIGN_TTL_SECONDS)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = DEFAULT_PRESIGN_TTL_SECONDS
    tenant_cap = config_json.get("presign_ttl_max_seconds", MAX_PRESIGN_TTL_SECONDS)
    try:
        cap = min(int(tenant_cap), MAX_PRESIGN_TTL_SECONDS)
    except (TypeError, ValueError):
        cap = MAX_PRESIGN_TTL_SECONDS
    return min(max(ttl, 60), cap)


def expire_stale_upload(
    *,
    expires_at: datetime,
    current: UploadStatus,
    now: datetime,
) -> UploadStatus:
    if current is UploadStatus.PENDING and expires_at < now:
        return UploadStatus.EXPIRED
    return current


@dataclass
class UploadRecord:
    id: uuid.UUID
    document_id: uuid.UUID
    status: UploadStatus
    presigned_url_issued_at: datetime
    expires_at: datetime
    expected_s3_key: str
    s3_bucket: str


@dataclass
class TenantConfigRecord:
    tenant_id: uuid.UUID
    config_json: dict[str, Any] = field(default_factory=dict)


class TenantConfigService(Protocol):
    async def get_config(self, *, tenant_id: uuid.UUID) -> dict[str, Any]: ...


class InMemoryTenantConfigService:
    def __init__(self) -> None:
        self._configs: dict[uuid.UUID, dict[str, Any]] = {}

    def seed(self, tenant_id: uuid.UUID, config_json: dict[str, Any]) -> None:
        self._configs[tenant_id] = dict(config_json)

    async def get_config(self, *, tenant_id: uuid.UUID) -> dict[str, Any]:
        return dict(self._configs.get(tenant_id, {}))


class SqlAlchemyTenantConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_config(self, *, tenant_id: uuid.UUID) -> dict[str, Any]:
        row = await self._session.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if row is None:
            return {}
        return dict(row.config_json or {})


class UploadService(Protocol):
    async def presign(
        self,
        *,
        tenant_id: uuid.UUID,
        body: PresignRequest,
        s3_client: BaseClient,
        settings: Settings,
    ) -> PresignResponse: ...

    async def has_expired_upload(self, *, document_id: uuid.UUID) -> bool: ...


class InMemoryUploadService:
    def __init__(
        self,
        document_service: DocumentService,
        tenant_config_service: TenantConfigService,
    ) -> None:
        self._documents = document_service
        self._tenant_config = tenant_config_service
        self._uploads: dict[uuid.UUID, UploadRecord] = {}

    @property
    def uploads(self) -> dict[uuid.UUID, UploadRecord]:
        return self._uploads

    async def has_expired_upload(self, *, document_id: uuid.UUID) -> bool:
        return any(
            u.document_id == document_id and u.status is UploadStatus.EXPIRED
            for u in self._uploads.values()
        )

    async def presign(
        self,
        *,
        tenant_id: uuid.UUID,
        body: PresignRequest,
        s3_client: BaseClient,
        settings: Settings,
    ) -> PresignResponse:
        record = await self._documents.get(tenant_id=tenant_id, document_id=body.document_id)
        config = await self._tenant_config.get_config(tenant_id=tenant_id)
        return await _presign_for_document(
            record=record,
            body=body,
            s3_client=s3_client,
            settings=settings,
            config=config,
            persist_upload=self._persist_upload,
            transition_document=self._transition_document,
        )

    async def _persist_upload(self, upload: UploadRecord) -> None:
        self._uploads[upload.id] = upload

    async def _transition_document(
        self,
        record: DocumentRecord,
        *,
        s3_bucket: str,
        s3_key: str,
    ) -> None:
        record.status = transition(record.status, DocumentStatus.UPLOADING)
        _ = s3_bucket, s3_key


class SqlAlchemyUploadService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_config_service: TenantConfigService,
    ) -> None:
        self._session = session
        self._tenant_config = tenant_config_service

    async def has_expired_upload(self, *, document_id: uuid.UUID) -> bool:
        row = await self._session.scalar(
            select(Upload).where(
                Upload.document_id == document_id,
                Upload.status == UploadStatus.EXPIRED.value,
            )
        )
        return row is not None

    async def presign(
        self,
        *,
        tenant_id: uuid.UUID,
        body: PresignRequest,
        s3_client: BaseClient,
        settings: Settings,
    ) -> PresignResponse:
        row = await self._session.scalar(
            select(Document).where(
                Document.id == body.document_id,
                Document.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise NotFoundError("Document not found")

        record = DocumentRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            document_type=DocumentType(row.document_type),
            status=DocumentStatus(row.status),
            external_ref=row.external_ref,
            idempotency_key=row.idempotency_key,
            title=row.title,
            metadata=dict(row.metadata_json or {}),
            file_name=row.file_name,
            mime_type=row.mime_type,
            checksum_sha256=row.checksum_sha256,
            file_size_bytes=row.file_size_bytes,
            created_by=row.created_by,
            correlation_id=uuid.UUID(int=0),
            created_at=row.created_at,
        )
        config = await self._tenant_config.get_config(tenant_id=tenant_id)

        async def persist_upload(upload: UploadRecord) -> None:
            self._session.add(
                Upload(
                    id=upload.id,
                    document_id=upload.document_id,
                    status=upload.status.value,
                    presigned_url_issued_at=upload.presigned_url_issued_at,
                    expires_at=upload.expires_at,
                    expected_s3_key=upload.expected_s3_key,
                )
            )

        async def transition_document(
            doc_record: DocumentRecord,
            *,
            s3_bucket: str,
            s3_key: str,
        ) -> None:
            row.status = transition(doc_record.status, DocumentStatus.UPLOADING).value
            row.s3_bucket = s3_bucket
            row.s3_key = s3_key

        response = await _presign_for_document(
            record=record,
            body=body,
            s3_client=s3_client,
            settings=settings,
            config=config,
            persist_upload=persist_upload,
            transition_document=transition_document,
        )
        await self._session.commit()
        return response


async def _presign_for_document(
    *,
    record: DocumentRecord,
    body: PresignRequest,
    s3_client: BaseClient,
    settings: Settings,
    config: dict[str, Any],
    persist_upload: Any,
    transition_document: Any,
) -> PresignResponse:
    allowed = allowed_mime_types_for_tenant(config)
    if body.content_type not in allowed:
        raise ValidationError(
            f"content_type {body.content_type!r} is not allowed for this tenant",
        )

    if record.status is not DocumentStatus.DRAFT:
        raise ValidationError(
            f"document must be DRAFT to presign (current: {record.status})",
        )

    file_name = record.file_name or "upload.bin"
    s3_key = build_object_key(record.tenant_id, record.id, file_name)
    ttl = presign_ttl_seconds_for_tenant(config)

    result: PresignResult = create_presigned_put(
        s3_client,
        bucket=settings.s3_bucket,
        key=s3_key,
        content_type=body.content_type,
        checksum_sha256=body.checksum_sha256,
        expires_in=ttl,
        kms_key_id=settings.s3_kms_key_id,
    )

    upload_id = generate_uuidv7()
    issued_at = datetime.now(UTC)
    upload = UploadRecord(
        id=upload_id,
        document_id=record.id,
        status=UploadStatus.PENDING,
        presigned_url_issued_at=issued_at,
        expires_at=result.expires_at,
        expected_s3_key=s3_key,
        s3_bucket=settings.s3_bucket,
    )
    await persist_upload(upload)
    await transition_document(record, s3_bucket=settings.s3_bucket, s3_key=s3_key)

    return PresignResponse(
        upload_id=upload_id,
        presigned_url=result.presigned_url,
        method=result.method,
        expires_at=result.expires_at,
        s3_bucket=result.s3_bucket,
        s3_key=result.s3_key,
        required_headers=result.required_headers,
    )
