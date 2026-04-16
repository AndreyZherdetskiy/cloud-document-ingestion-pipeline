from uuid import UUID

import pytest

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.hooks.types import HookContext

DOC_ID = UUID("01900000-0000-7000-8000-000000000001")


def _ctx() -> HookContext:
    return HookContext(
        tenant_id=UUID("01900000-0000-7000-8000-0000000000aa"),
        document_id=DOC_ID,
        document_type=DocumentType.INVOICE,
        bucket="bucket",
        key="t/d/f.pdf",
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
    )


@pytest.mark.asyncio
async def test_virus_stub_clean_true() -> None:
    result = await StubVirusScanHook(clean=True).scan(_ctx())
    assert result.clean is True
    assert result.scanner
    assert result.scan_id


@pytest.mark.asyncio
async def test_virus_stub_clean_false() -> None:
    result = await StubVirusScanHook(clean=False).scan(_ctx())
    assert result.clean is False


@pytest.mark.asyncio
async def test_ocr_and_extract_deterministic() -> None:
    ocr_a = await StubOcrHook().run(_ctx())
    ocr_b = await StubOcrHook().run(_ctx())
    assert ocr_a == ocr_b
    ext = await StubExtractHook().run(_ctx(), ocr_a)
    assert ext.document_type is DocumentType.INVOICE
    assert isinstance(ext.payload, dict)
