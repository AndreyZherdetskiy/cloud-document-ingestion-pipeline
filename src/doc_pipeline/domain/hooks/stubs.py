import asyncio
import hashlib
from collections.abc import Callable
from uuid import UUID

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.hooks.types import (
    ExtractResult,
    HookContext,
    OcrResult,
    VirusScanResult,
)

STUB_SCANNER = "stub-clamav"
STUB_OCR_PROVIDER = "stub-textract"


def _deterministic_seed(document_id: UUID, checksum_sha256: str | None) -> str:
    material = f"{document_id}:{checksum_sha256 or ''}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _scan_id(document_id: UUID, checksum_sha256: str | None) -> str:
    return f"scan-{_deterministic_seed(document_id, checksum_sha256)}"


def _ocr_preview(document_id: UUID, checksum_sha256: str | None) -> str:
    return f"stub-ocr-{_deterministic_seed(document_id, checksum_sha256)}"


def _ocr_pages(document_id: UUID) -> int:
    return (document_id.int % 5) + 1


def _ocr_confidence(document_id: UUID) -> float:
    return 0.5 + (document_id.int % 50) / 100.0


def _extract_payload(ctx: HookContext) -> dict[str, object]:
    seed = _deterministic_seed(ctx.document_id, ctx.checksum_sha256)
    match ctx.document_type:
        case DocumentType.INVOICE:
            return {
                "invoice_number": f"INV-{seed}",
                "amount_cents": ctx.document_id.int % 100000,
                "currency": "EUR",
            }
        case DocumentType.KYC:
            return {
                "document_ref": f"KYC-{seed}",
                "verified": True,
            }
        case DocumentType.CONTRACT:
            return {
                "contract_id": f"CTR-{seed}",
                "parties": 2,
            }
        case _ as unreachable:
            raise AssertionError(f"unknown document type: {unreachable}")


async def _maybe_sleep(
    sleep_ms: int,
    jitter_ms: int,
    jitter_fn: Callable[[], int] | None,
) -> None:
    if sleep_ms <= 0:
        return
    extra = jitter_fn() if jitter_fn is not None else jitter_ms
    await asyncio.sleep((sleep_ms + extra) / 1000.0)


class StubVirusScanHook:
    def __init__(
        self,
        clean: bool = True,
        sleep_ms: int = 0,
        jitter_ms: int = 0,
        jitter_fn: Callable[[], int] | None = None,
    ) -> None:
        self._clean = clean
        self._sleep_ms = sleep_ms
        self._jitter_ms = jitter_ms
        self._jitter_fn = jitter_fn

    async def scan(self, ctx: HookContext) -> VirusScanResult:
        await _maybe_sleep(self._sleep_ms, self._jitter_ms, self._jitter_fn)
        return VirusScanResult(
            clean=self._clean,
            scanner=STUB_SCANNER,
            scan_id=_scan_id(ctx.document_id, ctx.checksum_sha256),
        )


class StubOcrHook:
    def __init__(
        self,
        sleep_ms: int = 0,
        jitter_ms: int = 0,
        jitter_fn: Callable[[], int] | None = None,
    ) -> None:
        self._sleep_ms = sleep_ms
        self._jitter_ms = jitter_ms
        self._jitter_fn = jitter_fn

    async def run(self, ctx: HookContext) -> OcrResult:
        await _maybe_sleep(self._sleep_ms, self._jitter_ms, self._jitter_fn)
        return OcrResult(
            provider=STUB_OCR_PROVIDER,
            pages=_ocr_pages(ctx.document_id),
            text_preview=_ocr_preview(ctx.document_id, ctx.checksum_sha256),
            confidence=_ocr_confidence(ctx.document_id),
        )


class StubExtractHook:
    def __init__(
        self,
        sleep_ms: int = 0,
        jitter_ms: int = 0,
        jitter_fn: Callable[[], int] | None = None,
    ) -> None:
        self._sleep_ms = sleep_ms
        self._jitter_ms = jitter_ms
        self._jitter_fn = jitter_fn

    async def run(self, ctx: HookContext, ocr: OcrResult) -> ExtractResult:
        await _maybe_sleep(self._sleep_ms, self._jitter_ms, self._jitter_fn)
        return ExtractResult(
            document_type=ctx.document_type,
            payload=_extract_payload(ctx),
        )
