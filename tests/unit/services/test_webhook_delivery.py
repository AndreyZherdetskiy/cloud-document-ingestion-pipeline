import httpx
import pytest

from doc_pipeline.domain.services.webhook_service import deliver_webhook


@pytest.mark.asyncio
async def test_deliver_webhook_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, request=request)
        assert request.headers.get("X-Webhook-Signature", "").startswith("sha256=")
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await deliver_webhook(
            http_client=client,
            url="https://example.test/hooks",
            secret="s",
            payload={"event_type": "document.failed", "data": {}},
            max_attempts=3,
        )
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_deliver_webhook_skips_when_already_terminal() -> None:
    """Idempotent guard: no HTTP when document already PROCESSED/FAILED (caller passes flag)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await deliver_webhook(
            http_client=client,
            url="https://example.test/hooks",
            secret="s",
            payload={"event_type": "document.processed", "data": {}},
            max_attempts=3,
            skip=True,  # implementer: skip=True when status already terminal
        )
    assert calls["n"] == 0
