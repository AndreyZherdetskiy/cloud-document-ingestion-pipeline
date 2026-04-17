from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.errors import InvalidTransitionError

ALLOWED: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.DRAFT: frozenset({DocumentStatus.UPLOADING, DocumentStatus.CANCELLED}),
    DocumentStatus.UPLOADING: frozenset({DocumentStatus.UPLOADED, DocumentStatus.CANCELLED}),
    # UPLOADED/QUEUED → FAILED: invalid MIME / intake validation (spec §4.6).
    DocumentStatus.UPLOADED: frozenset(
        {DocumentStatus.QUEUED, DocumentStatus.FAILED, DocumentStatus.CANCELLED}
    ),
    DocumentStatus.QUEUED: frozenset(
        {DocumentStatus.SCANNING, DocumentStatus.FAILED, DocumentStatus.CANCELLED}
    ),
    DocumentStatus.SCANNING: frozenset(
        {DocumentStatus.EXTRACTING, DocumentStatus.FAILED, DocumentStatus.CANCELLED}
    ),
    DocumentStatus.EXTRACTING: frozenset(
        {DocumentStatus.PROCESSED, DocumentStatus.FAILED, DocumentStatus.CANCELLED}
    ),
    DocumentStatus.PROCESSED: frozenset(),
    DocumentStatus.FAILED: frozenset(),
    DocumentStatus.CANCELLED: frozenset(),
}


def can_transition(src: DocumentStatus, dst: DocumentStatus) -> bool:
    return dst in ALLOWED[src]


def transition(src: DocumentStatus, dst: DocumentStatus) -> DocumentStatus:
    if not can_transition(src, dst):
        raise InvalidTransitionError(from_status=src, to_status=dst)
    return dst
