"""Enforce append-only audit_log: REVOKE PUBLIC + mutation trigger (ADR-003).

Revision ID: 20260414_0002
Revises: 20260414_0001
Create Date: 2026-04-14

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from doc_pipeline.infrastructure.db.audit_append_only import (
    append_only_downgrade_statements,
    append_only_upgrade_statements,
)

revision: str = "20260414_0002"
down_revision: str | None = "20260414_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for statement in append_only_upgrade_statements():
        op.execute(text(statement))


def downgrade() -> None:
    for statement in append_only_downgrade_statements():
        op.execute(text(statement))
