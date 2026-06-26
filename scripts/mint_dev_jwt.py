#!/usr/bin/env python3
"""Mint a dev RS256 JWT for local API calls — token only on stdout."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

import jwt
from sqlalchemy import select

from doc_pipeline.config.settings import get_settings
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker

DEFAULT_ROLES = ("ROLE_API_CLIENT",)


def mint_jwt(
    *,
    private_pem: str,
    tenant_id: uuid.UUID,
    roles: tuple[str, ...],
    issuer: str,
    audience: str,
    sub: str = "dev-mint",
) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "tenant_id": str(tenant_id),
            "roles": list(roles),
            "iss": issuer,
            "aud": audience,
        },
        private_pem,
        algorithm="RS256",
    )


async def lookup_tenant_id(slug: str) -> uuid.UUID:
    settings = get_settings()
    sessionmaker = get_async_sessionmaker(settings)
    async with sessionmaker() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            print(f"error: tenant slug {slug!r} not found — run make seed", file=sys.stderr)
            raise SystemExit(1)
        return tenant.id


async def _run(slug: str, roles: tuple[str, ...], sub: str) -> None:
    settings = get_settings()
    private_pem = settings.jwt_private_key_pem.strip()
    if not private_pem:
        print(
            "error: JWT_PRIVATE_KEY_PEM is empty — run make gen-dev-jwt and recreate api container",
            file=sys.stderr,
        )
        raise SystemExit(1)
    tenant_id = await lookup_tenant_id(slug)
    token = mint_jwt(
        private_pem=private_pem,
        tenant_id=tenant_id,
        roles=roles,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        sub=sub,
    )
    print(token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint dev JWT for local stub auth")
    parser.add_argument("--slug", default="acme", help="Tenant slug (default: acme)")
    parser.add_argument(
        "--roles",
        default=",".join(DEFAULT_ROLES),
        help="Comma-separated roles (default: ROLE_API_CLIENT)",
    )
    parser.add_argument("--sub", default="dev-mint", help="JWT sub claim")
    args = parser.parse_args()
    roles = tuple(r.strip() for r in args.roles.split(",") if r.strip())
    if not roles:
        print("error: at least one role required", file=sys.stderr)
        raise SystemExit(1)
    asyncio.run(_run(args.slug, roles, args.sub))


if __name__ == "__main__":
    main()
