"""Unit tests for audit_log append-only DDL helpers (ADR-003)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from doc_pipeline.infrastructure.db.audit_append_only import (
    append_only_downgrade_statements,
    append_only_upgrade_statements,
)


def _load_revision_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260414_0002_audit_log_append_only.py"
    )
    spec = importlib.util.spec_from_file_location("rev_20260414_0002_audit_log_append_only", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upgrade_sql_contains_revoke_and_trigger() -> None:
    statements = append_only_upgrade_statements()
    joined = "\n".join(statements)
    assert "REVOKE UPDATE, DELETE ON TABLE audit_log FROM PUBLIC" in joined
    assert "BEFORE UPDATE OR DELETE ON audit_log" in joined
    assert "RAISE EXCEPTION" in joined


def test_downgrade_sql_drops_trigger_and_restores_grants() -> None:
    statements = append_only_downgrade_statements()
    joined = "\n".join(statements)
    assert "DROP TRIGGER" in joined
    assert "audit_log" in joined
    assert "GRANT UPDATE, DELETE ON TABLE audit_log TO PUBLIC" in joined


def test_alembic_upgrade_executes_helper_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    rev = _load_revision_module()
    executed: list[str] = []

    def _capture(sql: object) -> None:
        executed.append(str(sql))

    monkeypatch.setattr(rev.op, "execute", _capture)
    rev.upgrade()
    joined = "\n".join(executed)
    assert "REVOKE UPDATE, DELETE ON TABLE audit_log FROM PUBLIC" in joined
    assert "BEFORE UPDATE OR DELETE ON audit_log" in joined
