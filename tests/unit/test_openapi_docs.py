import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from doc_pipeline.main import create_app

REQUIRED_TAGS = {"documents", "uploads", "jobs", "audit", "admin", "health"}
FORBIDDEN_PROSE = ("spec.md", "ADR-", ".superpowers", ".docs_ru", "AGENTS.md")
SNAPSHOT_JSON = Path(__file__).resolve().parents[2] / "docs" / "openapi" / "openapi.json"


def test_openapi_info_and_tags() -> None:
    app = create_app()
    spec = app.openapi()
    assert spec["info"]["title"] == "Cloud Document Ingestion Pipeline"
    assert spec["info"].get("summary")
    assert spec["info"].get("description")
    serialized = json.dumps(spec)
    for bad in FORBIDDEN_PROSE:
        assert bad not in serialized
    servers = {s.get("url") for s in spec.get("servers", [])}
    assert "http://localhost:8000" in servers
    tag_names = {t["name"] for t in spec.get("tags", [])}
    assert tag_names >= REQUIRED_TAGS
    for t in spec["tags"]:
        assert t.get("description"), t["name"]


@pytest.mark.parametrize("needle", ["presign", "JWT", "404", "problem"])
def test_openapi_info_description_mentions(needle: str) -> None:
    desc = create_app().openapi()["info"]["description"]
    assert needle.lower() in desc.lower() or needle in desc


def test_every_operation_has_summary_and_description() -> None:
    spec = create_app().openapi()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method.startswith("x-"):
                continue
            assert op.get("summary"), f"{method.upper()} {path}"
            assert op.get("description"), f"{method.upper()} {path}"


def test_v1_docs_serves_swagger_html() -> None:
    client = TestClient(create_app())
    r = client.get("/v1/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()


@pytest.mark.parametrize(
    ("path", "expected_location"),
    [
        ("/docs", "/v1/docs"),
        ("/docs/", "/v1/docs"),
    ],
)
def test_docs_redirects_to_v1_docs(path: str, expected_location: str) -> None:
    client = TestClient(create_app())
    r = client.get(path, follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == expected_location


@pytest.mark.parametrize(
    ("path", "expected_location"),
    [
        ("/redoc", "/v1/redoc"),
        ("/redoc/", "/v1/redoc"),
    ],
)
def test_redoc_redirects_to_v1_redoc(path: str, expected_location: str) -> None:
    client = TestClient(create_app())
    r = client.get(path, follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == expected_location


def test_openapi_documents_headers_and_examples() -> None:
    spec = create_app().openapi()
    create_op = spec["paths"]["/v1/documents"]["post"]
    assert create_op.get("summary") and create_op.get("description")
    params = {p["name"]: p for p in create_op.get("parameters", [])}
    assert "Idempotency-Key" in params
    assert params["Idempotency-Key"].get("description")
    assert "Authorization" in params
    assert params["Authorization"].get("description")
    assert create_op.get("requestBody")
    # Body openapi_examples surface as requestBody content examples
    content = create_op["requestBody"]["content"]["application/json"]
    assert content.get("examples") or content.get("schema")
    create_responses = create_op.get("responses", {})
    assert "409" in create_responses, "POST /v1/documents must document 409"
    assert "429" in create_responses, "POST /v1/documents must document 429"
    assert "401" in create_responses
    assert "422" in create_responses

    get_op = spec["paths"]["/v1/documents/{document_id}"]["get"]
    assert "404" in get_op.get("responses", {})

    presign_op = spec["paths"]["/v1/uploads/presign"]["post"]
    assert presign_op.get("summary") and presign_op.get("description")
    presign_responses = presign_op.get("responses", {})
    assert "400" in presign_responses
    assert "401" in presign_responses
    assert "422" in presign_responses
    presign_body = presign_op.get("requestBody", {})
    presign_content = presign_body["content"]["application/json"]
    assert presign_content.get("examples") or presign_content.get("schema")

    retry_op = spec["paths"]["/v1/jobs/{job_id}/retry"]["post"]
    retry_responses = retry_op.get("responses", {})
    assert "409" in retry_responses, "POST /v1/jobs/{job_id}/retry must document 409"
    assert "403" in retry_responses, "POST /v1/jobs/{job_id}/retry must document 403"
    assert "Authorization" in {p["name"]: p for p in retry_op.get("parameters", [])}
    assert {p["name"]: p for p in retry_op.get("parameters", [])}["Authorization"].get(
        "description"
    )

    cancel_job = spec["paths"]["/v1/jobs/{job_id}/cancel"]["post"]
    assert "403" in cancel_job.get("responses", {})
    assert "409" in cancel_job.get("responses", {})

    audit_op = spec["paths"]["/v1/audit"]["get"]
    assert "403" in audit_op.get("responses", {})
    assert "Authorization" in {p["name"]: p for p in audit_op.get("parameters", [])}

    dlq_op = spec["paths"]["/v1/admin/dlq/replay"]["post"]
    assert "403" in dlq_op.get("responses", {})
    assert "Authorization" in {p["name"]: p for p in dlq_op.get("parameters", [])}


def test_openapi_presign_field_descriptions() -> None:
    spec = create_app().openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    assert "PresignRequest" in schemas
    for name, prop in schemas["PresignRequest"]["properties"].items():
        assert prop.get("description"), f"PresignRequest.{name} missing description"
    presign_response = schemas.get("PresignResponse")
    assert presign_response is not None
    for name, prop in presign_response["properties"].items():
        assert prop.get("description"), f"PresignResponse.{name} missing description"


def test_openapi_field_descriptions_and_enums_no_integer_id() -> None:
    spec = create_app().openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    assert "DocumentCreate" in schemas, schemas.keys()
    create = schemas["DocumentCreate"]
    props = create.get("properties", {})
    for name, prop in props.items():
        assert prop.get("description"), f"DocumentCreate.{name} missing description"
    assert "document_type" in props
    doc_type = props["document_type"]
    # Enum — not bare string
    assert (
        doc_type.get("enum") or "$ref" in doc_type or ("anyOf" in doc_type or "allOf" in doc_type)
    )

    response = schemas.get("DocumentResponse")
    assert response is not None
    id_schema = response["properties"]["id"]
    assert id_schema.get("type") != "integer"
    assert id_schema.get("format") == "uuid" or "uuid" in json.dumps(id_schema).lower()

    status_prop = response["properties"]["status"]
    assert status_prop.get("enum") or "$ref" in status_prop or "anyOf" in status_prop

    serialized = json.dumps(spec)
    for bad in FORBIDDEN_PROSE:
        assert bad not in serialized


def test_openapi_snapshot_paths_match_live() -> None:
    live = create_app().openapi()
    assert SNAPSHOT_JSON.is_file(), "run make export-openapi"
    snapshot = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    assert set(snapshot.get("paths", {})) == set(live.get("paths", {}))
