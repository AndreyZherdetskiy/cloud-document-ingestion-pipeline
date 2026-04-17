"""Outbound webhook HMAC signing and delivery (side effect after terminal status)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import httpx
import structlog
from opentelemetry import metrics
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_none,
)

from doc_pipeline.observability.otel import assert_low_cardinality_attrs

logger = structlog.get_logger(__name__)

WebhookEventType = Literal["document.processed", "document.failed"]


class _RetryableWebhookError(Exception):
    """Transient delivery failure (5xx / timeout / transport)."""


def sign_webhook_body(*, secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_webhook_payload(
    *,
    event_type: WebhookEventType,
    event_id: UUID,
    occurred_at: datetime,
    tenant_id: UUID,
    document_id: UUID,
    status: str,
    external_ref: str | None,
    processing_result: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "event_id": str(event_id),
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "tenant_id": str(tenant_id),
        "data": {
            "document_id": str(document_id),
            "status": status,
            "external_ref": external_ref,
            "processing_result": processing_result,
        },
    }


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableWebhookError | httpx.TimeoutException | httpx.TransportError)


def _record_webhook_exhausted(*, event_type: str) -> None:
    try:
        meter = metrics.get_meter("doc_pipeline.worker")
        counter = meter.create_counter("webhook_delivery_exhausted")
        attrs = assert_low_cardinality_attrs({"event_type": event_type})
        counter.add(1, attrs)
    except Exception:
        return


async def deliver_webhook(
    *,
    http_client: httpx.AsyncClient,
    url: str,
    secret: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
    skip: bool = False,
    timeout_seconds: float = 5.0,
) -> None:
    """POST signed JSON; retries 5xx/timeouts; never raises after terminal commit."""
    if skip:
        return

    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    signature = sign_webhook_body(secret=secret, body=body)
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
    }
    event_type = str(payload.get("event_type", "unknown"))

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_none(),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                try:
                    response = await http_client.post(
                        url,
                        content=body,
                        headers=headers,
                        timeout=timeout_seconds,
                    )
                except (httpx.TimeoutException, httpx.TransportError):
                    raise
                if response.status_code >= 500:
                    raise _RetryableWebhookError(f"webhook HTTP {response.status_code}")
                if response.status_code >= 400:
                    logger.warning(
                        "webhook_delivery_client_error",
                        status_code=response.status_code,
                        event_type=event_type,
                    )
                    return
    except Exception as exc:
        logger.error(
            "webhook_delivery_exhausted",
            event_type=event_type,
            error=str(exc),
            max_attempts=max_attempts,
        )
        _record_webhook_exhausted(event_type=event_type)
        return
