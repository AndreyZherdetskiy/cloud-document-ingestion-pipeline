"""UUIDv7 generation for domain primary keys (ADR-012)."""

from __future__ import annotations

import uuid

from uuid6 import uuid7


def generate_uuidv7() -> uuid.UUID:
    """Return a time-ordered UUID version 7 (RFC 9562)."""
    return uuid7()
