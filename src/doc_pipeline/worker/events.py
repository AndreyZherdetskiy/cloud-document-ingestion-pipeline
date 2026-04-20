"""Parse SQS / S3 ObjectCreated envelopes and PROCESS_DOCUMENT messages (spec §7.4–7.5)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import unquote_plus
from uuid import UUID

from doc_pipeline.domain.enums import DocumentType


class IgnorableSqsPayload(Exception):
    """SQS body is valid infrastructure noise; ACK without document processing."""


@dataclass(frozen=True, slots=True)
class S3IngestEvent:
    bucket: str
    object_key: str
    etag: str | None
    tenant_id: UUID
    document_id: UUID
    event_name: str | None = None
    schema_version: str = "1"
    event_source: str = "aws:s3"
    correlation_id: UUID | None = None
    object_size: int | None = None


@dataclass(frozen=True, slots=True)
class ProcessDocumentMessage:
    schema_version: str
    message_type: Literal["PROCESS_DOCUMENT"]
    job_id: UUID
    document_id: UUID
    tenant_id: UUID
    document_type: DocumentType
    s3_bucket: str
    s3_key: str
    attempt: int
    correlation_id: UUID
    requested_hooks: tuple[str, ...]


def serialize_process_document_message(msg: ProcessDocumentMessage) -> str:
    payload = asdict(msg)
    payload["job_id"] = str(msg.job_id)
    payload["document_id"] = str(msg.document_id)
    payload["tenant_id"] = str(msg.tenant_id)
    payload["correlation_id"] = str(msg.correlation_id)
    payload["document_type"] = msg.document_type.value
    payload["requested_hooks"] = list(msg.requested_hooks)
    return json.dumps(payload)


def parse_process_document_message(body: str) -> ProcessDocumentMessage:
    payload: dict[str, Any] = json.loads(body)
    message_type = payload.get("message_type")
    if message_type != "PROCESS_DOCUMENT":
        msg = f"expected message_type PROCESS_DOCUMENT, got {message_type!r}"
        raise ValueError(msg)
    hooks_raw = payload.get("requested_hooks") or ()
    return ProcessDocumentMessage(
        schema_version=str(payload.get("schema_version") or "1"),
        message_type="PROCESS_DOCUMENT",
        job_id=UUID(str(payload["job_id"])),
        document_id=UUID(str(payload["document_id"])),
        tenant_id=UUID(str(payload["tenant_id"])),
        document_type=DocumentType(str(payload["document_type"])),
        s3_bucket=str(payload["s3_bucket"]),
        s3_key=str(payload["s3_key"]),
        attempt=int(payload.get("attempt") or 1),
        correlation_id=UUID(str(payload["correlation_id"])),
        requested_hooks=tuple(str(h) for h in hooks_raw),
    )


def parse_tenant_document_from_key(object_key: str) -> tuple[UUID, UUID]:
    """Extract tenant_id and document_id from `{tenant_id}/{document_id}/filename`."""
    parts = object_key.strip("/").split("/")
    if len(parts) < 3:
        msg = f"object_key must be tenant_id/document_id/filename, got {object_key!r}"
        raise ValueError(msg)
    return UUID(parts[0]), UUID(parts[1])


def parse_s3_event_message(body: str | dict[str, Any]) -> S3IngestEvent:
    """Normalize a logical envelope or raw S3 event JSON into ``S3IngestEvent``."""
    payload: dict[str, Any] = json.loads(body) if isinstance(body, str) else body

    # SNS → SQS wrapping (Stage 1 LocalStack may deliver either shape).
    if "Message" in payload and isinstance(payload["Message"], str):
        payload = json.loads(payload["Message"])

    if _is_s3_test_event(payload):
        raise IgnorableSqsPayload("s3:TestEvent")

    if "Records" in payload:
        return _from_s3_records(payload)

    return _from_logical_envelope(payload)


def _is_s3_test_event(payload: dict[str, Any]) -> bool:
    if payload.get("Event") == "s3:TestEvent":
        return True
    return payload.get("Service") == "Amazon S3" and "Records" not in payload


def _from_logical_envelope(payload: dict[str, Any]) -> S3IngestEvent:
    object_key = str(payload["object_key"])
    if "tenant_id" in payload and "document_id" in payload:
        tenant_id = UUID(str(payload["tenant_id"]))
        document_id = UUID(str(payload["document_id"]))
    else:
        tenant_id, document_id = parse_tenant_document_from_key(object_key)

    correlation_raw = payload.get("correlation_id")
    correlation_id = UUID(str(correlation_raw)) if correlation_raw else None
    size_raw = payload.get("object_size")
    object_size = int(size_raw) if size_raw is not None else None

    return S3IngestEvent(
        bucket=str(payload["bucket"]),
        object_key=object_key,
        etag=str(payload["etag"]) if payload.get("etag") is not None else None,
        tenant_id=tenant_id,
        document_id=document_id,
        event_name=str(payload["event_name"]) if payload.get("event_name") else None,
        schema_version=str(payload.get("schema_version") or "1"),
        event_source=str(payload.get("event_source") or "aws:s3"),
        correlation_id=correlation_id,
        object_size=object_size,
    )


def _from_s3_records(payload: dict[str, Any]) -> S3IngestEvent:
    records = payload.get("Records") or []
    if not records:
        raise ValueError("S3 event has empty Records")
    record = records[0]
    s3 = record.get("s3") or {}
    bucket = (s3.get("bucket") or {}).get("name")
    obj = s3.get("object") or {}
    object_key = obj.get("key")
    if not bucket or not object_key:
        raise ValueError("S3 record missing bucket/key")
    # S3 may URL-encode keys in notifications.
    object_key = unquote_plus(str(object_key))
    tenant_id, document_id = parse_tenant_document_from_key(object_key)
    size_raw = obj.get("size")
    return S3IngestEvent(
        bucket=str(bucket),
        object_key=object_key,
        etag=str(obj["eTag"]).strip('"') if obj.get("eTag") is not None else None,
        tenant_id=tenant_id,
        document_id=document_id,
        event_name=str(record.get("eventName")) if record.get("eventName") else None,
        event_source=str(record.get("eventSource") or "aws:s3"),
        object_size=int(size_raw) if size_raw is not None else None,
    )
