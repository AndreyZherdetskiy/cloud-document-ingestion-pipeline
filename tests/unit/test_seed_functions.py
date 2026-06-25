"""Unit tests for seed_dev / seed_prod_like (import + call — no script grep)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import boto3
import pytest
from moto import mock_aws

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.seed.dev import seed_dev
from doc_pipeline.seed.prod_like import seed_prod_like


class FakeSeedSession:
    """In-memory async session supporting slug / idempotency lookup + add/commit."""

    def __init__(self) -> None:
        self.tenants_by_slug: dict[str, Tenant] = {}
        self.tenants_by_id: dict[UUID, Tenant] = {}
        self.documents: dict[tuple[UUID, str], Document] = {}
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, Tenant):
            self.tenants_by_slug[obj.slug] = obj
            self.tenants_by_id[obj.id] = obj
        elif isinstance(obj, Document):
            self.documents[(obj.tenant_id, obj.idempotency_key)] = obj

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        return None

    async def scalar(self, stmt: object) -> Any | None:
        compiled = stmt.compile()  # type: ignore[attr-defined]
        text = str(compiled).lower()
        params = dict(compiled.params)

        if "from tenants" in text or ("tenants." in text and "documents" not in text):
            slug = params.get("slug_1") or params.get("slug")
            if slug is not None:
                return self.tenants_by_slug.get(str(slug))
            tid = params.get("id_1") or params.get("id")
            if tid is not None:
                return self.tenants_by_id.get(tid)
            return None

        if "documents" in text:
            tenant_id = params.get("tenant_id_1") or params.get("tenant_id")
            idem = params.get("idempotency_key_1") or params.get("idempotency_key")
            if tenant_id is not None and idem is not None:
                return self.documents.get((tenant_id, str(idem)))
            return None

        return None


@pytest.fixture
def settings() -> Settings:
    return Settings(otel_sdk_disabled=True, aws_region="eu-central-1", s3_bucket="dev-doc-pipeline")


@pytest.fixture
def db_session() -> FakeSeedSession:
    return FakeSeedSession()


@pytest.fixture
def s3_moto(settings: Settings):
    with mock_aws():
        client = boto3.client("s3", region_name=settings.aws_region)
        client.create_bucket(
            Bucket=settings.s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
        )
        yield client


@pytest.mark.asyncio
async def test_seed_dev_upserts_acme(
    db_session: FakeSeedSession,
    s3_moto: Any,
    settings: Settings,
) -> None:
    report1 = await seed_dev(db_session, s3_moto, settings)
    report2 = await seed_dev(db_session, s3_moto, settings)
    assert report1.tenant_slug == "acme"
    assert report2.tenant_slug == "acme"
    assert report1.tenants_created == 1
    assert report2.tenants_created == 0
    assert 1 <= report1.s3_objects_created <= 3
    assert report2.documents_created == 0


@pytest.mark.asyncio
async def test_seed_dev_jwt_note_has_no_secrets(
    db_session: FakeSeedSession,
    s3_moto: Any,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await seed_dev(db_session, s3_moto, settings)
    out = capsys.readouterr().out
    assert "JWT" in out or "jwt" in out.lower()
    assert "BEGIN" not in out
    assert "PRIVATE" not in out
    assert settings.jwt_public_key_pem not in out


@pytest.mark.asyncio
async def test_seed_prod_like_mix_and_fixtures(
    db_session: FakeSeedSession,
    s3_moto: Any,
    settings: Settings,
) -> None:
    report = await seed_prod_like(db_session, s3_moto, settings)
    assert report.tenants_created >= 2
    types = {d.document_type for d in db_session.documents.values()}
    assert DocumentType.INVOICE.value in types
    assert DocumentType.KYC.value in types
    assert DocumentType.CONTRACT.value in types

    virus = [
        d
        for d in db_session.documents.values()
        if d.metadata_json.get("fixture") == "virus_stub_fail"
    ]
    invalid = [
        d for d in db_session.documents.values() if d.metadata_json.get("fixture") == "invalid_mime"
    ]
    assert len(virus) == 1
    assert len(invalid) == 1
    assert invalid[0].mime_type is not None
    assert invalid[0].mime_type not in {
        "application/pdf",
        "image/png",
        "image/jpeg",
    }

    report2 = await seed_prod_like(db_session, s3_moto, settings)
    assert report2.tenants_created == 0
    assert report2.documents_created == 0
