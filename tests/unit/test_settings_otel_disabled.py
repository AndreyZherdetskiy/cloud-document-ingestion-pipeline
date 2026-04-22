from doc_pipeline.config.settings import Settings


def test_empty_otel_sdk_disabled_is_false(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "")
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
        "-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----",
    )
    s = Settings(_env_file=None)
    assert s.otel_sdk_disabled is False
