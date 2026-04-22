"""Unit tests for documents_processed counter attributes."""

from __future__ import annotations

from opentelemetry import metrics

from doc_pipeline.worker.handlers import _record_documents_processed


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str]]] = []

    def add(self, amount: int, attrs: dict[str, str]) -> None:
        self.calls.append((amount, attrs))


class _FakeMeter:
    def __init__(self, counter: _FakeCounter) -> None:
        self._counter = counter

    def create_counter(self, name: str) -> _FakeCounter:
        assert name == "documents_processed"
        return self._counter


def test_record_documents_processed_includes_tenant_slug(monkeypatch) -> None:
    counter = _FakeCounter()
    monkeypatch.setattr(metrics, "get_meter", lambda _name: _FakeMeter(counter))

    _record_documents_processed(
        status="PROCESSED",
        document_type="INVOICE",
        tenant_slug="acme",
    )

    assert counter.calls == [
        (
            1,
            {
                "status": "PROCESSED",
                "document_type": "INVOICE",
                "tenant_slug": "acme",
            },
        ),
    ]
