"""Authenticated caller identity from JWT claims."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    sub: str
    tenant_id: uuid.UUID
    roles: frozenset[str]
