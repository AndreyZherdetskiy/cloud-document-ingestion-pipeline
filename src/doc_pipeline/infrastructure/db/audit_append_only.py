"""SQL statements enforcing append-only ``audit_log`` (ADR-003).

Alembic revisions import these helpers so unit tests can assert the DDL without
inventory-grepping migration files.
"""

from __future__ import annotations

_TRIGGER_FUNCTION = "prevent_audit_log_mutation"
_TRIGGER_NAME = "trg_audit_log_append_only"


def append_only_upgrade_statements() -> tuple[str, ...]:
    """DDL applied on upgrade: REVOKE PUBLIC + owner-blocking trigger."""
    return (
        "REVOKE UPDATE, DELETE ON TABLE audit_log FROM PUBLIC;",
        f"""
CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: UPDATE/DELETE are not permitted';
END;
$$;
""".strip(),
        f"""
CREATE TRIGGER {_TRIGGER_NAME}
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION {_TRIGGER_FUNCTION}();
""".strip(),
    )


def append_only_downgrade_statements() -> tuple[str, ...]:
    """DDL applied on downgrade: drop trigger/function and restore PUBLIC grants."""
    return (
        f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON audit_log;",
        f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}();",
        "GRANT UPDATE, DELETE ON TABLE audit_log TO PUBLIC;",
    )
