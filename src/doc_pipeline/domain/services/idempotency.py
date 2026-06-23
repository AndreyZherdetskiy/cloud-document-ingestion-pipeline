"""Redis processing lock for at-least-once SQS ingest (ADR-002)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

_LOCK_KEY_PREFIX = "doc:processing:"
_INGEST_LOCK_KEY_PREFIX = "doc:ingest:"


class RedisSetNx(Protocol):
    async def set_nx(self, key: str, value: str, *, ex: int | None = None) -> bool: ...


def processing_lock_key(document_id: UUID) -> str:
    return f"{_LOCK_KEY_PREFIX}{document_id}"


def ingest_lock_key(document_id: UUID) -> str:
    return f"{_INGEST_LOCK_KEY_PREFIX}{document_id}"


async def acquire_processing_lock(
    redis: RedisSetNx,
    document_id: UUID,
    ttl_seconds: int = 600,
) -> bool:
    """SET NX EX — True when this worker owns the processing lock for document_id."""
    return await redis.set_nx(
        processing_lock_key(document_id),
        "1",
        ex=ttl_seconds,
    )


async def acquire_ingest_lock(
    redis: RedisSetNx,
    document_id: UUID,
    ttl_seconds: int = 600,
) -> bool:
    """SET NX EX — True when this worker owns the ingest enqueue lock."""
    return await redis.set_nx(
        ingest_lock_key(document_id),
        "1",
        ex=ttl_seconds,
    )
