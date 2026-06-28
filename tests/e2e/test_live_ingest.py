"""Live ingest happy path and tenant isolation against Compose."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from tests.e2e import conftest as e2e_conftest
from tests.e2e.conftest import (
    DEFAULT_ROLES,
    POLL_INTERVAL_SECONDS,
    POLL_TIMEOUT_SECONDS,
    lookup_tenant_id,
    mint_jwt,
)

from doc_pipeline.domain.ids import generate_uuidv7

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_live_demo_module() -> ModuleType:
    sys.modules.setdefault("mint_dev_jwt", e2e_conftest._mint_dev_jwt)
    spec = importlib.util.spec_from_file_location(
        "live_ingest_demo",
        REPO_ROOT / "scripts" / "live_ingest_demo.py",
    )
    if spec is None or spec.loader is None:
        msg = "cannot load live_ingest_demo.py"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_live_demo = _load_live_demo_module()
_put_presigned = _live_demo._put_presigned
_OBJECT_BODY = _live_demo._OBJECT_BODY


def _checksum_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _auth_headers(token: str, correlation_id: str, idempotency_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
        "X-Correlation-ID": correlation_id,
    }


def _poll_document_processed(
    http_client: httpx.Client,
    *,
    base_url: str,
    document_id: str,
    token: str,
) -> str:
    poll_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    final_status = "UNKNOWN"
    while time.monotonic() < deadline:
        doc_res = http_client.get(f"{base_url}/v1/documents/{document_id}", headers=poll_headers)
        assert doc_res.status_code == 200, doc_res.text
        final_status = doc_res.json()["status"]
        if final_status == "PROCESSED":
            return final_status
        if final_status in ("FAILED", "CANCELLED"):
            pytest.fail(f"document reached terminal status {final_status!r}")
        time.sleep(POLL_INTERVAL_SECONDS)
    pytest.fail(
        f"timed out after {POLL_TIMEOUT_SECONDS}s waiting for PROCESSED (last={final_status!r})"
    )


def _create_and_upload_invoice(
    http_client: httpx.Client,
    *,
    base_url: str,
    token: str,
    external_ref: str,
    idempotency_prefix: str,
) -> str:
    checksum = _checksum_sha256(_OBJECT_BODY)
    correlation_id = str(generate_uuidv7())
    idempotency_key = f"{idempotency_prefix}-{correlation_id}"
    headers = _auth_headers(token, correlation_id, idempotency_key)

    create_body = {
        "document_type": "INVOICE",
        "external_ref": external_ref,
        "file_name": "e2e-invoice.pdf",
        "content_type": "application/pdf",
        "checksum_sha256": checksum,
    }
    create_res = http_client.post(f"{base_url}/v1/documents", json=create_body, headers=headers)
    assert create_res.status_code in (200, 201), create_res.text
    document_id = create_res.json()["id"]

    presign_body = {
        "document_id": document_id,
        "content_type": "application/pdf",
        "checksum_sha256": checksum,
    }
    presign_res = http_client.post(
        f"{base_url}/v1/uploads/presign",
        json=presign_body,
        headers=headers,
    )
    assert presign_res.status_code == 200, presign_res.text

    presign_payload = presign_res.json()
    put_url = presign_payload["presigned_url"]
    required_headers = presign_payload.get("required_headers") or {}
    put_status = _put_presigned(put_url, _OBJECT_BODY, required_headers)
    assert 200 <= put_status < 300, f"S3 PUT failed status={put_status}"

    return document_id


def test_create_presign_put_reaches_processed(
    api_base_url: str,
    auth_token_acme: str,
    http_client: httpx.Client,
) -> None:
    document_id = _create_and_upload_invoice(
        http_client,
        base_url=api_base_url,
        token=auth_token_acme,
        external_ref="e2e-live-ingest",
        idempotency_prefix="e2e-ingest",
    )
    status = _poll_document_processed(
        http_client,
        base_url=api_base_url,
        document_id=document_id,
        token=auth_token_acme,
    )
    assert status == "PROCESSED"


def test_foreign_tenant_document_is_404(
    api_base_url: str,
    auth_token_acme: str,
    http_client: httpx.Client,
) -> None:
    from doc_pipeline.config.settings import get_settings

    document_id = _create_and_upload_invoice(
        http_client,
        base_url=api_base_url,
        token=auth_token_acme,
        external_ref="e2e-tenant-404",
        idempotency_prefix="e2e-tenant-404",
    )

    private_pem = get_settings().jwt_private_key_pem.strip()
    try:
        globex_tenant_id = asyncio.run(lookup_tenant_id("globex"))
    except SystemExit:
        pytest.skip("globex tenant missing — run `make seed-prod-like`")

    globex_token = mint_jwt(
        private_pem=private_pem,
        tenant_id=globex_tenant_id,
        roles=DEFAULT_ROLES,
        issuer=get_settings().jwt_issuer,
        audience=get_settings().jwt_audience,
        sub="e2e-globex",
    )
    response = http_client.get(
        f"{api_base_url}/v1/documents/{document_id}",
        headers={
            "Authorization": f"Bearer {globex_token}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 404, response.text
