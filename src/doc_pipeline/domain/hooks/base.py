from typing import Protocol

from doc_pipeline.domain.hooks.types import (
    ExtractResult,
    HookContext,
    OcrResult,
    VirusScanResult,
)


class VirusScanHook(Protocol):
    async def scan(self, ctx: HookContext) -> VirusScanResult: ...


class OcrHook(Protocol):
    async def run(self, ctx: HookContext) -> OcrResult: ...


class ExtractHook(Protocol):
    async def run(self, ctx: HookContext, ocr: OcrResult) -> ExtractResult: ...
