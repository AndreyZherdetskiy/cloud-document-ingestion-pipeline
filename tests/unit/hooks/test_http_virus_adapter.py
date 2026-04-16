import httpx
import pytest

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.hooks.adapters.http_virus import HttpVirusScanHook
from doc_pipeline.domain.hooks.types import HookContext
from doc_pipeline.domain.ids import generate_uuidv7


@pytest.mark.asyncio
async def test_http_virus_adapter_maps_clean_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"clean": False, "scanner": "clamav-http", "scan_id": "s-1"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hook = HttpVirusScanHook(client=client, base_url="https://av.test/scan")
        ctx = HookContext(
            tenant_id=generate_uuidv7(),
            document_id=generate_uuidv7(),
            document_type=DocumentType.INVOICE,
            bucket="b",
            key="k",
            mime_type="application/pdf",
            checksum_sha256="abc",
        )
        result = await hook.scan(ctx)
    assert result.clean is False
    assert result.scanner == "clamav-http"
    assert result.scan_id == "s-1"


@pytest.mark.asyncio
async def test_http_virus_adapter_raises_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hook = HttpVirusScanHook(client=client, base_url="https://av.test/scan")
        ctx = HookContext(
            tenant_id=generate_uuidv7(),
            document_id=generate_uuidv7(),
            document_type=DocumentType.INVOICE,
            bucket="b",
            key="k",
            mime_type="application/pdf",
            checksum_sha256="abc",
        )
        with pytest.raises(httpx.HTTPStatusError):
            await hook.scan(ctx)
