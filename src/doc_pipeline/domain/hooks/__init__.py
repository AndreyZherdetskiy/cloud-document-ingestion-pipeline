from doc_pipeline.domain.hooks.base import ExtractHook, OcrHook, VirusScanHook
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.hooks.types import (
    ExtractResult,
    HookContext,
    OcrResult,
    VirusScanResult,
)

__all__ = [
    "ExtractHook",
    "ExtractResult",
    "HookContext",
    "OcrHook",
    "OcrResult",
    "StubExtractHook",
    "StubOcrHook",
    "StubVirusScanHook",
    "VirusScanHook",
    "VirusScanResult",
]
