import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from doc_pipeline.api.auth.token_verifier import StubJwtVerifier, get_token_verifier
from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.ids import generate_uuidv7


def _rsa_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def test_stub_verifier_returns_principal() -> None:
    private_pem, public_pem = _rsa_pair()
    tenant_id = generate_uuidv7()
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        aws_region="eu-central-1",
        s3_bucket="b",
        sqs_queue_url="http://localhost/q",
        sqs_dlq_url="http://localhost/dlq",
        jwt_issuer="http://localhost:8000/dev-issuer",
        jwt_audience="doc-pipeline",
        jwt_public_key_pem=public_pem,
        auth_backend="stub",
    )
    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": str(tenant_id),
            "roles": ["ROLE_OPERATOR"],
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        private_pem,
        algorithm="RS256",
    )
    verifier = get_token_verifier(settings)
    assert isinstance(verifier, StubJwtVerifier)
    principal = verifier.verify(token)
    assert principal.sub == "user-1"
    assert principal.tenant_id == tenant_id
    assert "ROLE_OPERATOR" in principal.roles
