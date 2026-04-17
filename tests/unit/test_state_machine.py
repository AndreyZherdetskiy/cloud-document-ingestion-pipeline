import pytest

from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.errors import InvalidTransitionError
from doc_pipeline.domain.state_machine import can_transition, transition


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (DocumentStatus.DRAFT, DocumentStatus.UPLOADING),
        (DocumentStatus.UPLOADING, DocumentStatus.UPLOADED),
        (DocumentStatus.UPLOADING, DocumentStatus.CANCELLED),
        (DocumentStatus.UPLOADED, DocumentStatus.QUEUED),
        (DocumentStatus.UPLOADED, DocumentStatus.FAILED),
        (DocumentStatus.QUEUED, DocumentStatus.SCANNING),
        (DocumentStatus.QUEUED, DocumentStatus.FAILED),
        (DocumentStatus.QUEUED, DocumentStatus.CANCELLED),
        (DocumentStatus.SCANNING, DocumentStatus.EXTRACTING),
        (DocumentStatus.SCANNING, DocumentStatus.FAILED),
        (DocumentStatus.EXTRACTING, DocumentStatus.PROCESSED),
        (DocumentStatus.EXTRACTING, DocumentStatus.FAILED),
    ],
)
def test_allowed_transitions(src: DocumentStatus, dst: DocumentStatus) -> None:
    assert can_transition(src, dst) is True
    assert transition(src, dst) is dst


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (DocumentStatus.DRAFT, DocumentStatus.PROCESSED),
        (DocumentStatus.PROCESSED, DocumentStatus.QUEUED),
        (DocumentStatus.PROCESSED, DocumentStatus.CANCELLED),
        (DocumentStatus.FAILED, DocumentStatus.SCANNING),
        (DocumentStatus.CANCELLED, DocumentStatus.UPLOADING),
    ],
)
def test_invalid_transitions_raise(src: DocumentStatus, dst: DocumentStatus) -> None:
    assert can_transition(src, dst) is False
    with pytest.raises(InvalidTransitionError) as exc_info:
        transition(src, dst)
    assert exc_info.value.from_status is src
    assert exc_info.value.to_status is dst
