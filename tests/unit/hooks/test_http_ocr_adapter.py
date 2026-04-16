import httpx
import pytest

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.hooks.adapters.http_ocr import HttpOcrHook
from doc_pipeline.domain.hooks.types import HookContext
from doc_pipeline.domain.ids import generate_uuidv7


@pytest.mark.asyncio
async def test_http_ocr_adapter_maps_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "provider": "tesseract-http",
                "pages": 2,
                "text_preview": "Invoice #123",
                "confidence": 0.91,
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hook = HttpOcrHook(client=client, base_url="https://ocr.test/run")
        ctx = HookContext(
            tenant_id=generate_uuidv7(),
            document_id=generate_uuidv7(),
            document_type=DocumentType.INVOICE,
            bucket="b",
            key="k",
            mime_type="application/pdf",
            checksum_sha256="abc",
        )
        result = await hook.run(ctx)
    assert result.provider == "tesseract-http"
    assert result.pages == 2
    assert result.text_preview == "Invoice #123"
    assert result.confidence == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_http_ocr_adapter_raises_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hook = HttpOcrHook(client=client, base_url="https://ocr.test/run")
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
            await hook.run(ctx)
