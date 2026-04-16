from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.hooks.adapters.http_ocr import HttpOcrHook
from doc_pipeline.domain.hooks.adapters.http_virus import HttpVirusScanHook
from doc_pipeline.domain.hooks.base import ExtractHook, OcrHook, VirusScanHook
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook


def _build_virus_hook(settings: Settings) -> VirusScanHook:
    match settings.virus_hook_backend:
        case "stub":
            return StubVirusScanHook(clean=settings.stub_virus_clean)
        case "http":
            if not settings.virus_scan_url:
                raise ValueError("virus_hook_backend=http requires VIRUS_SCAN_URL")
            return HttpVirusScanHook(base_url=settings.virus_scan_url)
        case _ as unreachable:
            raise AssertionError(f"unknown virus hook backend: {unreachable}")


def _build_ocr_hook(settings: Settings) -> OcrHook:
    match settings.ocr_hook_backend:
        case "stub":
            return StubOcrHook()
        case "http":
            if not settings.ocr_url:
                raise ValueError("ocr_hook_backend=http requires OCR_URL")
            return HttpOcrHook(base_url=settings.ocr_url)
        case _ as unreachable:
            raise AssertionError(f"unknown ocr hook backend: {unreachable}")


def build_hooks(settings: Settings) -> tuple[VirusScanHook, OcrHook, ExtractHook]:
    return (
        _build_virus_hook(settings),
        _build_ocr_hook(settings),
        StubExtractHook(),
    )
