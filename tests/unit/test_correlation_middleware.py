from fastapi.testclient import TestClient

from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.main import create_app


def test_missing_correlation_generates_uuidv7() -> None:
    client = TestClient(create_app())
    r = client.get("/v1/health")
    assert r.status_code == 200
    cid = r.headers.get("X-Correlation-ID") or r.headers.get("x-correlation-id")
    assert cid
    assert cid[14] == "7"


def test_invalid_correlation_422() -> None:
    client = TestClient(create_app())
    r = client.get("/v1/health", headers={"X-Correlation-ID": "not-a-uuid"})
    assert r.status_code == 422
    assert r.headers.get("content-type", "").startswith("application/problem+json")


def test_valid_correlation_echoed() -> None:
    cid = str(generate_uuidv7())
    client = TestClient(create_app())
    r = client.get("/v1/health", headers={"X-Correlation-Id": cid})
    assert r.status_code == 200
    assert r.headers.get("X-Correlation-ID") == cid


def test_non_v7_uuid_422() -> None:
    import uuid

    client = TestClient(create_app())
    r = client.get("/v1/health", headers={"X-Correlation-ID": str(uuid.uuid4())})
    assert r.status_code == 422
    assert r.headers.get("content-type", "").startswith("application/problem+json")
