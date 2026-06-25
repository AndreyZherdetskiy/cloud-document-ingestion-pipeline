import pytest

from doc_pipeline.observability.otel import assert_low_cardinality_attrs


def test_rejects_high_card_keys() -> None:
    with pytest.raises(ValueError):
        assert_low_cardinality_attrs({"document_id": "x"})
    with pytest.raises(ValueError):
        assert_low_cardinality_attrs({"correlation_id": "y"})
    result = assert_low_cardinality_attrs({"tenant_slug": "acme", "document_type": "INVOICE"})
    assert result == {"tenant_slug": "acme", "document_type": "INVOICE"}
