"""JWT verification — stub issuer and Cognito swap skeleton (ADR-013)."""

from __future__ import annotations

import uuid
from typing import Protocol

import jwt

from doc_pipeline.api.auth.principal import Principal
from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.errors import UnauthorizedError


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Principal: ...


class StubJwtVerifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._settings.jwt_public_key_pem,
                algorithms=["RS256"],
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                options={"require": ["sub", "tenant_id", "roles", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid or expired JWT") from exc

        try:
            tenant_id = uuid.UUID(str(claims["tenant_id"]))
        except (ValueError, TypeError, KeyError) as exc:
            raise UnauthorizedError("JWT tenant_id must be a UUID") from exc

        raw_roles = claims.get("roles") or []
        if not isinstance(raw_roles, list):
            raise UnauthorizedError("JWT roles must be a list")
        roles = frozenset(str(r) for r in raw_roles)
        sub = str(claims["sub"])
        return Principal(sub=sub, tenant_id=tenant_id, roles=roles)


class CognitoJwtVerifier:
    """JWKS skeleton — maps sub, custom:tenant_id, cognito:groups → Principal."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def verify(self, token: str) -> Principal:
        raise NotImplementedError("Cognito requires AWS account; use auth_backend=stub")


def get_token_verifier(settings: Settings) -> TokenVerifier:
    if settings.auth_backend == "cognito":
        return CognitoJwtVerifier(settings)
    return StubJwtVerifier(settings)
