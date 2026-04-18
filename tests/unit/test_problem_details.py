import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from doc_pipeline.api.errors import problem_response, register_exception_handlers
from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.errors import InvalidTransitionError


def test_problem_response_media_type_and_shape() -> None:
    resp = problem_response(422, "Unprocessable Entity", "bad input")
    assert resp.status_code == 422
    assert resp.media_type == "application/problem+json"
    body = json.loads(resp.body)
    assert body == {
        "type": "about:blank",
        "title": "Unprocessable Entity",
        "status": 422,
        "detail": "bad input",
    }


def test_invalid_transition_returns_409_problem_json() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise InvalidTransitionError(DocumentStatus.DRAFT, DocumentStatus.PROCESSED)

    r = TestClient(app).get("/boom")
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 409
    assert "DRAFT" in body["detail"]
    assert "PROCESSED" in body["detail"]


def test_request_validation_returns_422_problem_json() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    class Payload(BaseModel):
        name: str = Field(min_length=3)

    @app.post("/items")
    def create_item(payload: Payload) -> dict[str, str]:
        return {"name": payload.name}

    r = TestClient(app).post("/items", json={"name": "ab"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 422
    assert body["title"] == "Unprocessable Entity"
