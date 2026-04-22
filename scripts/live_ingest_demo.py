#!/usr/bin/env python3
"""FROM_ZERO happy path — create → presign → S3 PUT → poll PROCESSED → audit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

import httpx

from doc_pipeline.config.settings import get_settings
from doc_pipeline.domain.ids import generate_uuidv7
from mint_dev_jwt import DEFAULT_ROLES, lookup_tenant_id, mint_jwt

_OBJECT_BODY = b"live-demo-pdf-bytes\n"
_DEFAULT_POLL_INTERVAL = 2.0
_DEFAULT_POLL_TIMEOUT = 180.0
_LIVE_DEMO_ROLES = (*DEFAULT_ROLES, "ROLE_OPERATOR")


def _checksum_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _rewrite_localstack_hostname_for_host_put() -> bool:
    return not (
        os.environ.get("LIVE_DEMO_IN_NETWORK", "").strip() == "1"
        or os.environ.get("S3_PUT_REWRITE_LOCALSTACK", "").strip() == "0"
    )


def _resolve_s3_put_url(url: str) -> tuple[str, str | None]:
    parsed = urlparse(url)
    if parsed.hostname != "localstack" or not _rewrite_localstack_hostname_for_host_put():
        return url, None
    put_url = urlunparse(parsed._replace(netloc=f"127.0.0.1:{parsed.port or 4566}"))
    return put_url, parsed.netloc


def _put_presigned(url: str, body: bytes, required_headers: dict[str, str]) -> int:
    headers = dict(required_headers)
    put_url, host_override = _resolve_s3_put_url(url)
    # Host/WSL: presign returns localstack; map to 127.0.0.1 for published port access.
    if host_override is not None:
        headers["Host"] = host_override
    request = urllib.request.Request(put_url, data=body, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", errors="replace")
        print(f"error: S3 PUT HTTPError status={exc.code} body={detail}", file=sys.stderr)
        return int(exc.code)


async def _resolve_auth_token(base_url: str) -> str:
    env_token = os.environ.get("AUTH_TOKEN", "").strip()
    if env_token:
        return env_token

    settings = get_settings()
    private_pem = settings.jwt_private_key_pem.strip()
    if not private_pem:
        print(
            "error: AUTH_TOKEN unset and JWT_PRIVATE_KEY_PEM empty — "
            "run make gen-dev-jwt, recreate api, or set AUTH_TOKEN",
            file=sys.stderr,
        )
        raise SystemExit(1)

    tenant_id = await lookup_tenant_id("acme")
    return mint_jwt(
        private_pem=private_pem,
        tenant_id=tenant_id,
        roles=_LIVE_DEMO_ROLES,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        sub="live-ingest-demo",
    )


def _auth_headers(token: str, correlation_id: str, idempotency_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
        "X-Correlation-ID": correlation_id,
    }


async def _run(
    base_url: str,
    poll_interval: float,
    poll_timeout: float,
) -> None:
    token = await _resolve_auth_token(base_url)
    checksum = _checksum_sha256(_OBJECT_BODY)
    correlation_id = str(generate_uuidv7())
    idempotency_key = f"live-demo-{correlation_id}"

    create_body = {
        "document_type": "INVOICE",
        "external_ref": "live-demo-ref",
        "file_name": "live-demo.pdf",
        "content_type": "application/pdf",
        "checksum_sha256": checksum,
    }

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        headers = _auth_headers(token, correlation_id, idempotency_key)
        create_res = await client.post("/v1/documents", json=create_body, headers=headers)
        if create_res.status_code == 401:
            print(
                "error: POST /v1/documents returned 401 — "
                "JWT/PEM mismatch; run make gen-dev-jwt, recreate api, "
                f"body={create_res.text[:500]}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if create_res.status_code not in (200, 201):
            print(
                f"error: POST /v1/documents failed status={create_res.status_code} "
                f"body={create_res.text[:500]}",
                file=sys.stderr,
            )
            raise SystemExit(1)

        document_id = create_res.json()["id"]
        print(f"document_id={document_id} create_status={create_res.status_code}")

        presign_body = {
            "document_id": document_id,
            "content_type": "application/pdf",
            "checksum_sha256": checksum,
        }
        presign_res = await client.post(
            "/v1/uploads/presign",
            json=presign_body,
            headers=headers,
        )
        if presign_res.status_code != 200:
            print(
                f"error: POST /v1/uploads/presign failed status={presign_res.status_code} "
                f"body={presign_res.text[:500]}",
                file=sys.stderr,
            )
            raise SystemExit(1)

        presign_payload = presign_res.json()
        upload_id = presign_payload["upload_id"]
        put_url = presign_payload["presigned_url"]
        required_headers = presign_payload.get("required_headers") or {}
        print(f"upload_id={upload_id} presign_status=200")

        put_status = await asyncio.to_thread(
            _put_presigned, put_url, _OBJECT_BODY, required_headers
        )
        if put_status < 200 or put_status >= 300:
            print(f"error: S3 PUT failed status={put_status}", file=sys.stderr)
            raise SystemExit(1)
        print(f"s3_put_status={put_status}")

        poll_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        deadline = time.monotonic() + poll_timeout
        final_status = "UNKNOWN"
        while time.monotonic() < deadline:
            doc_res = await client.get(f"/v1/documents/{document_id}", headers=poll_headers)
            if doc_res.status_code != 200:
                print(
                    f"error: GET document failed status={doc_res.status_code}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            final_status = doc_res.json()["status"]
            print(f"poll status={final_status}")
            if final_status == "PROCESSED":
                break
            if final_status in ("FAILED", "CANCELLED"):
                print(f"error: document terminal status={final_status}", file=sys.stderr)
                raise SystemExit(1)
            await asyncio.sleep(poll_interval)
        else:
            print(
                f"error: timed out after {poll_timeout}s waiting for PROCESSED "
                f"(last={final_status})",
                file=sys.stderr,
            )
            raise SystemExit(1)

        audit_res = await client.get(
            "/v1/audit",
            params={"document_id": document_id},
            headers=poll_headers,
        )
        if audit_res.status_code == 403:
            print("audit_status=403 (ROLE_OPERATOR required for audit read)")
        elif audit_res.status_code != 200:
            print(f"audit_status={audit_res.status_code}")
        else:
            event_types = [item["event_type"] for item in audit_res.json().get("items", [])]
            print(f"audit_status=200 event_types={event_types}")

        print(f"RESULT=PROCESSED document_id={document_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live ingest demo against running API")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "http://localhost:8000"),
        help="API base URL (default: BASE_URL env or http://localhost:8000)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=_DEFAULT_POLL_INTERVAL,
        help="Seconds between status polls",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=_DEFAULT_POLL_TIMEOUT,
        help="Max seconds to wait for PROCESSED",
    )
    args = parser.parse_args()
    asyncio.run(
        _run(
            args.base_url.rstrip("/"),
            args.poll_interval,
            args.poll_timeout,
        )
    )


if __name__ == "__main__":
    main()
