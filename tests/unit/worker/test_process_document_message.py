import json
from uuid import UUID

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.worker.events import (
    ProcessDocumentMessage,
    parse_process_document_message,
    serialize_process_document_message,
)


def test_process_document_round_trip() -> None:
    msg = ProcessDocumentMessage(
        schema_version="1",
        message_type="PROCESS_DOCUMENT",
        job_id=generate_uuidv7(),
        document_id=generate_uuidv7(),
        tenant_id=generate_uuidv7(),
        document_type=DocumentType.INVOICE,
        s3_bucket="dev-doc-pipeline",
        s3_key="t/d/file.pdf",
        attempt=1,
        correlation_id=generate_uuidv7(),
        requested_hooks=("virus", "ocr", "extract"),
    )
    raw = serialize_process_document_message(msg)
    parsed = parse_process_document_message(raw)
    assert parsed.message_type == "PROCESS_DOCUMENT"
    assert parsed.document_id == msg.document_id
    assert parsed.document_type == DocumentType.INVOICE
    assert "virus" in parsed.requested_hooks
    body = json.loads(raw)
    assert body["message_type"] == "PROCESS_DOCUMENT"
    UUID(str(body["correlation_id"]))
