import hashlib
import hmac
import json
from datetime import UTC, datetime

from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.services.webhook_service import (
    build_webhook_payload,
    sign_webhook_body,
)


def test_sign_webhook_body_sha256_hex() -> None:
    secret = "test-secret"
    body = b'{"event_type":"document.processed"}'
    sig = sign_webhook_body(secret=secret, body=body)
    assert sig.startswith("sha256=")
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sig == f"sha256={digest}"


def test_build_webhook_payload_shape() -> None:
    eid = generate_uuidv7()
    tid = generate_uuidv7()
    did = generate_uuidv7()
    payload = build_webhook_payload(
        event_type="document.processed",
        event_id=eid,
        occurred_at=datetime(2026, 6, 17, 12, 0, tzinfo=UTC),
        tenant_id=tid,
        document_id=did,
        status="PROCESSED",
        external_ref="EXT-1",
        processing_result={"pages": 1},
    )
    assert payload["event_type"] == "document.processed"
    assert payload["event_id"] == str(eid)
    assert payload["tenant_id"] == str(tid)
    assert payload["data"]["document_id"] == str(did)
    assert payload["data"]["status"] == "PROCESSED"
    json.dumps(payload)  # serializable
