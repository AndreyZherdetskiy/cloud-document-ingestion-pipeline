"""Seed report DTO shared by seed_dev and seed_prod_like."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SeedReport:
    tenant_slug: str
    tenants_created: int
    documents_created: int
    s3_objects_created: int
    queues_ok: bool
