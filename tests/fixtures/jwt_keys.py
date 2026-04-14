"""RSA keypair and JWT minting for unit tests (dev issuer stub)."""

from __future__ import annotations

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
PUBLIC_PEM = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)

DEFAULT_ISSUER = "http://localhost:8000/dev-issuer"
DEFAULT_AUDIENCE = "doc-pipeline"


def mint_token(
    *,
    tenant_id: str,
    roles: list[str],
    sub: str = "user-1",
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "tenant_id": tenant_id,
            "roles": roles,
            "iss": issuer,
            "aud": audience,
        },
        PRIVATE_PEM,
        algorithm="RS256",
    )
