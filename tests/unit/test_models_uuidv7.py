"""UUIDv7 PK and schema invariant tests for domain models (spec §6.0–6.6, ADR-012)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import BigInteger
from sqlalchemy import inspect as sa_inspect

from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models import Base
from doc_pipeline.domain.models.audit_log import AuditLog
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.job import Job
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.domain.models.upload import Upload

STAGE1_TABLES = frozenset(
    {
        "tenants",
        "documents",
        "uploads",
        "jobs",
        "audit_log",
    }
)

UUID_PK_MODELS = (Tenant, Document, Upload, Job, AuditLog)


def test_generate_uuidv7_is_version_7() -> None:
    value = generate_uuidv7()
    assert isinstance(value, uuid.UUID)
    assert value.version == 7


def test_document_pk_is_uuid_only() -> None:
    mapper = sa_inspect(Document)
    pk_cols = [c.name for c in mapper.primary_key]
    assert pk_cols == ["id"]
    col_names = {c.key for c in mapper.columns}
    assert "public_id" not in col_names
    assert "idempotency_key" in col_names
    assert "tenant_id" in col_names


def test_tenant_slug_unique() -> None:
    table = Tenant.__table__
    slug_in_constraint = any(
        "slug" in {col.name for col in constraint.columns}
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    )
    slug_in_index = any("slug" in index.name for index in table.indexes)
    assert slug_in_constraint or slug_in_index


def test_documents_tenant_idempotency_unique() -> None:
    constraints = {c.name: c for c in Document.__table__.constraints if c.name is not None}
    matching = [
        name
        for name, constraint in constraints.items()
        if {"tenant_id", "idempotency_key"} == {col.name for col in constraint.columns}
    ]
    assert matching, "expected UNIQUE (tenant_id, idempotency_key) on documents"


def test_documents_tenant_indexes() -> None:
    index_names = {index.name for index in Document.__table__.indexes}
    assert "ix_documents_tenant_status" in index_names
    assert "ix_documents_tenant_external_ref" in index_names
    assert "ix_documents_tenant_created_at" in index_names


def test_metadata_includes_stage1_tables_only() -> None:
    table_names = set(Base.metadata.tables)
    assert table_names == STAGE1_TABLES
    assert "job_steps" not in table_names


@pytest.mark.parametrize("model", UUID_PK_MODELS, ids=lambda m: m.__tablename__)
def test_model_primary_key_is_uuid(model: type) -> None:
    id_column = model.__table__.c.id
    assert str(id_column.type).upper().startswith("UUID")
    assert id_column.primary_key


def test_no_dual_id_bigint_identity() -> None:
    allowed_bigint = frozenset({("documents", "file_size_bytes")})
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name == "public_id":
                raise AssertionError(f"{table.name} has public_id column (dual-id forbidden)")
            if isinstance(column.type, BigInteger):
                key = (table.name, column.name)
                assert key in allowed_bigint, f"{table.name}.{column.name} unexpected BIGINT"
            if column.primary_key and isinstance(column.type, BigInteger):
                raise AssertionError(f"{table.name}.{column.name} uses BIGINT identity PK")


def test_audit_log_append_only_shape() -> None:
    assert AuditLog.__table__.c.tenant_id.nullable is False
    assert AuditLog.__table__.c.document_id.nullable is False
    assert AuditLog.__table__.c.job_id.nullable is True
    index_names = {index.name for index in AuditLog.__table__.indexes}
    assert "ix_audit_log_correlation_id" in index_names
    assert "ix_audit_log_created_at" in index_names
