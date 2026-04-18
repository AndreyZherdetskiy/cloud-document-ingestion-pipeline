"""FastAPI dependencies: JWT principal, Redis, document service, rate limit."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from botocore.client import BaseClient
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from doc_pipeline.api.auth.principal import Principal
from doc_pipeline.api.auth.token_verifier import get_token_verifier
from doc_pipeline.config.settings import Settings, get_settings
from doc_pipeline.domain.errors import (
    ForbiddenError,
    RateLimitExceededError,
    UnauthorizedError,
)
from doc_pipeline.domain.services.audit_service import (
    AuditService,
    InMemoryAuditService,
    SqlAlchemyAuditService,
)
from doc_pipeline.domain.services.dlq_service import DlqService, FakeDlqService, SqsDlqService
from doc_pipeline.domain.services.document_service import (
    DocumentService,
    InMemoryDocumentService,
    SqlAlchemyDocumentService,
)
from doc_pipeline.domain.services.job_service import (
    InMemoryJobService,
    JobService,
    SqlAlchemyJobService,
)
from doc_pipeline.domain.services.upload_service import (
    InMemoryTenantConfigService,
    InMemoryUploadService,
    SqlAlchemyTenantConfigService,
    SqlAlchemyUploadService,
    TenantConfigService,
    UploadService,
)
from doc_pipeline.infrastructure.aws.s3 import get_s3_client as build_s3_client
from doc_pipeline.infrastructure.aws.sqs import get_sqs_client as build_sqs_client
from doc_pipeline.infrastructure.cache.redis import (
    InMemoryRedisCache,
    RedisCache,
    RedisRateLimitClient,
)
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker

ROLE_API_CLIENT = "ROLE_API_CLIENT"
ROLE_OPERATOR = "ROLE_OPERATOR"
ROLE_COMPLIANCE = "ROLE_COMPLIANCE"
ROLE_ADMIN = "ROLE_ADMIN"
ROLE_PLATFORM_ADMIN = "ROLE_PLATFORM_ADMIN"
ROLE_SYSTEM = "ROLE_SYSTEM"

CREATE_DOCUMENT_ROLES = frozenset({ROLE_API_CLIENT, ROLE_ADMIN, ROLE_PLATFORM_ADMIN})
READ_DOCUMENT_ROLES = frozenset(
    {
        ROLE_API_CLIENT,
        ROLE_OPERATOR,
        ROLE_COMPLIANCE,
        ROLE_ADMIN,
        ROLE_PLATFORM_ADMIN,
    }
)
CANCEL_DOCUMENT_ROLES = frozenset(
    {
        ROLE_API_CLIENT,
        ROLE_OPERATOR,
        ROLE_ADMIN,
        ROLE_PLATFORM_ADMIN,
    }
)
READ_JOB_ROLES = frozenset(
    {
        ROLE_API_CLIENT,
        ROLE_OPERATOR,
        ROLE_COMPLIANCE,
        ROLE_ADMIN,
        ROLE_PLATFORM_ADMIN,
    }
)
RETRY_JOB_ROLES = frozenset({ROLE_OPERATOR, ROLE_PLATFORM_ADMIN})
CANCEL_JOB_ROLES = frozenset({ROLE_OPERATOR, ROLE_ADMIN, ROLE_PLATFORM_ADMIN})
READ_AUDIT_ROLES = frozenset(
    {
        ROLE_OPERATOR,
        ROLE_COMPLIANCE,
        ROLE_ADMIN,
        ROLE_PLATFORM_ADMIN,
    }
)
PLATFORM_ADMIN_ROLES = frozenset({ROLE_PLATFORM_ADMIN})

_AUTH_HEADER_DESCRIPTION = (
    "Bearer JWT (RS256); stub issuer locally, Cognito-compatible claims. Required. "
    "Missing or invalid token → 401. Claims: sub, tenant_id, roles."
)


def get_settings_dep() -> Settings:
    return get_settings()


def get_current_principal(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    authorization: Annotated[
        str | None,
        Header(alias="Authorization", description=_AUTH_HEADER_DESCRIPTION),
    ] = None,
) -> Principal:
    if authorization is None or not authorization.strip():
        raise UnauthorizedError("Missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise UnauthorizedError("Authorization must be Bearer <JWT>")
    token = parts[1].strip()
    return get_token_verifier(settings).verify(token)


def require_roles(principal: Principal, allowed: frozenset[str]) -> None:
    if principal.roles.isdisjoint(allowed):
        raise ForbiddenError("Caller role cannot perform this operation")


_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_redis: RedisCache | None = None


def _get_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = get_async_sessionmaker(settings)
    return _sessionmaker


async def get_db_session(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AsyncIterator[AsyncSession]:
    sessionmaker = _get_sessionmaker(settings)
    async with sessionmaker() as session:
        yield session


async def get_redis(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AsyncIterator[RedisCache]:
    global _redis
    if _redis is None:
        try:
            _redis = RedisRateLimitClient(settings.redis_url)
        except Exception:
            _redis = InMemoryRedisCache()
    yield _redis


async def get_document_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentService:
    return SqlAlchemyDocumentService(session)


def get_s3_client(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> BaseClient:
    return build_s3_client(settings)


async def get_tenant_config_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TenantConfigService:
    return SqlAlchemyTenantConfigService(session)


async def get_upload_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant_config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> UploadService:
    return SqlAlchemyUploadService(session, tenant_config)


async def get_job_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobService:
    return SqlAlchemyJobService(session)


async def get_audit_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuditService:
    return SqlAlchemyAuditService(session)


def get_sqs_client(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> BaseClient:
    return build_sqs_client(settings)


async def get_dlq_service(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    sqs_client: Annotated[BaseClient, Depends(get_sqs_client)],
) -> DlqService:
    return SqsDlqService(sqs_client, settings)


async def enforce_rate_limit(
    principal: Principal,
    redis: RedisCache,
    settings: Settings,
) -> None:
    key = f"rl:tenant:{principal.tenant_id}"
    allowed = await redis.check_rate_limit(
        key,
        limit=settings.rate_limit_per_minute,
        window_seconds=60,
    )
    if not allowed:
        raise RateLimitExceededError("Rate limit exceeded for this tenant")


# Re-export in-memory service type for tests/overrides typing convenience.
__all__ = [
    "CANCEL_DOCUMENT_ROLES",
    "CANCEL_JOB_ROLES",
    "CREATE_DOCUMENT_ROLES",
    "PLATFORM_ADMIN_ROLES",
    "Principal",
    "READ_AUDIT_ROLES",
    "READ_DOCUMENT_ROLES",
    "READ_JOB_ROLES",
    "RETRY_JOB_ROLES",
    "ROLE_API_CLIENT",
    "ROLE_OPERATOR",
    "ROLE_PLATFORM_ADMIN",
    "enforce_rate_limit",
    "get_audit_service",
    "get_current_principal",
    "get_db_session",
    "get_dlq_service",
    "get_document_service",
    "get_job_service",
    "get_redis",
    "get_s3_client",
    "get_settings_dep",
    "get_sqs_client",
    "get_tenant_config_service",
    "get_upload_service",
    "require_roles",
    "FakeDlqService",
    "InMemoryAuditService",
    "InMemoryDocumentService",
    "InMemoryJobService",
    "InMemoryTenantConfigService",
    "InMemoryUploadService",
]
