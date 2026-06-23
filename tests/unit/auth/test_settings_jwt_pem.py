"""Settings JWT PEM unescape and mint+verify with matching Settings keys."""

from __future__ import annotations

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from doc_pipeline.api.auth.token_verifier import StubJwtVerifier
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


def test_jwt_pem_unescapes_literal_backslash_n(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("S3_BUCKET", "dev-doc-pipeline")
    monkeypatch.setenv("SQS_QUEUE_URL", "http://localhost:4566/000000000000/q")
    monkeypatch.setenv("SQS_DLQ_URL", "http://localhost:4566/000000000000/dlq")
    monkeypatch.setenv("JWT_ISSUER", "http://localhost/issuer")
    monkeypatch.setenv("JWT_AUDIENCE", "doc-pipeline")
    monkeypatch.setenv(
        "JWT_PUBLIC_KEY_PEM",
        "-----BEGIN PUBLIC KEY-----\\nMIIB\\n-----END PUBLIC KEY-----",
    )
    monkeypatch.setenv(
        "JWT_PRIVATE_KEY_PEM",
        "-----BEGIN PRIVATE KEY-----\\nMIIB\\n-----END PRIVATE KEY-----",
    )
    monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", "")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", "")
    settings = Settings(_env_file=None)
    expected_public = "-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----"
    expected_private = "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----"
    assert settings.jwt_public_key_pem == expected_public
    assert settings.jwt_private_key_pem == expected_private


def test_mint_and_verify_with_settings_pem_pair() -> None:
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
        jwt_private_key_pem=private_pem,
        auth_backend="stub",
    )
    token = jwt.encode(
        {
            "sub": "settings-mint",
            "tenant_id": str(tenant_id),
            "roles": ["ROLE_API_CLIENT"],
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_private_key_pem,
        algorithm="RS256",
    )
    principal = StubJwtVerifier(settings).verify(token)
    assert principal.sub == "settings-mint"
    assert principal.tenant_id == tenant_id
    assert "ROLE_API_CLIENT" in principal.roles


def test_jwt_pem_loaded_from_path(tmp_path, monkeypatch) -> None:
    private_pem, public_pem = _rsa_pair()
    public_file = tmp_path / "public.pem"
    public_file.write_text(public_pem, encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("S3_BUCKET", "dev-doc-pipeline")
    monkeypatch.setenv("SQS_QUEUE_URL", "http://localhost:4566/000000000000/q")
    monkeypatch.setenv("SQS_DLQ_URL", "http://localhost:4566/000000000000/dlq")
    monkeypatch.setenv("JWT_ISSUER", "http://localhost/issuer")
    monkeypatch.setenv("JWT_AUDIENCE", "doc-pipeline")
    monkeypatch.setenv(
        "JWT_PUBLIC_KEY_PEM",
        "-----BEGIN PUBLIC KEY-----\\nstale\\n-----END PUBLIC KEY-----",
    )
    monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", str(public_file))
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", "")
    settings = Settings(_env_file=None)
    assert settings.jwt_public_key_pem == public_pem.strip()
