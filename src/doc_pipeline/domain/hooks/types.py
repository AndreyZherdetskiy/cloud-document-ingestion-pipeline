from dataclasses import dataclass
from uuid import UUID

from doc_pipeline.domain.enums import DocumentType


@dataclass(frozen=True)
class HookContext:
    tenant_id: UUID
    document_id: UUID
    document_type: DocumentType
    bucket: str
    key: str
    mime_type: str | None
    checksum_sha256: str | None


@dataclass(frozen=True)
class VirusScanResult:
    clean: bool
    scanner: str
    scan_id: str


@dataclass(frozen=True)
class OcrResult:
    provider: str
    pages: int
    text_preview: str
    confidence: float


@dataclass(frozen=True)
class ExtractResult:
    document_type: DocumentType
    payload: dict[str, object]
