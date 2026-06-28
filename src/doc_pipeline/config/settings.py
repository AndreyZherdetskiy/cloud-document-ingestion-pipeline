from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_STUB_JWT_PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAstub\n"
    "-----END PUBLIC KEY-----"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+asyncpg://test:test@localhost:5432/doc_pipeline",
        alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, alias="DATABASE_MAX_OVERFLOW")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    aws_endpoint_url: str | None = Field(default=None, alias="AWS_ENDPOINT_URL")
    aws_region: str = Field(default="eu-central-1", alias="AWS_REGION")
    s3_bucket: str = Field(default="dev-doc-pipeline", alias="S3_BUCKET")
    sqs_queue_url: str = Field(
        default="http://localhost:4566/000000000000/dev-document-ingestion",
        alias="SQS_QUEUE_URL",
    )
    sqs_dlq_url: str = Field(
        default="http://localhost:4566/000000000000/dev-document-ingestion-dlq",
        alias="SQS_DLQ_URL",
    )
    sqs_processing_queue_url: str = Field(
        default="http://localhost:4566/000000000000/dev-document-processing",
        alias="SQS_PROCESSING_QUEUE_URL",
    )
    sqs_processing_dlq_url: str = Field(
        default="http://localhost:4566/000000000000/dev-document-processing-dlq",
        alias="SQS_PROCESSING_DLQ_URL",
    )
    # Must match queue VisibilityTimeout (LocalStack/Terraform default 300; spec §5.4).
    sqs_visibility_timeout_seconds: int = Field(
        default=300,
        alias="SQS_VISIBILITY_TIMEOUT_SECONDS",
    )
    jwt_issuer: str = Field(default="http://localhost:8000/dev-issuer", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="doc-pipeline", alias="JWT_AUDIENCE")
    jwt_public_key_pem: str = Field(
        default=_STUB_JWT_PUBLIC_KEY_PEM,
        alias="JWT_PUBLIC_KEY_PEM",
    )
    jwt_private_key_pem: str = Field(default="", alias="JWT_PRIVATE_KEY_PEM")
    # Compose env_file splits unquoted PEM on \n; mount files instead (local demo).
    jwt_public_key_path: str = Field(default="", alias="JWT_PUBLIC_KEY_PATH")
    jwt_private_key_path: str = Field(default="", alias="JWT_PRIVATE_KEY_PATH")
    aws_access_key_id: str = Field(default="test", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="test", alias="AWS_SECRET_ACCESS_KEY")
    auth_backend: Literal["stub", "cognito"] = Field(default="stub", alias="AUTH_BACKEND")
    cognito_jwks_url: str | None = Field(default=None, alias="COGNITO_JWKS_URL")
    stub_virus_clean: bool = Field(default=True, alias="STUB_VIRUS_CLEAN")
    virus_hook_backend: Literal["stub", "http"] = Field(
        default="stub",
        alias="VIRUS_HOOK_BACKEND",
    )
    ocr_hook_backend: Literal["stub", "http"] = Field(
        default="stub",
        alias="OCR_HOOK_BACKEND",
    )
    virus_scan_url: str | None = Field(default=None, alias="VIRUS_SCAN_URL")
    ocr_url: str | None = Field(default=None, alias="OCR_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317",
        alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    otel_service_name: str = Field(default="doc-pipeline-api", alias="OTEL_SERVICE_NAME")
    otel_sdk_disabled: bool = Field(default=False, alias="OTEL_SDK_DISABLED")
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")
    s3_kms_key_id: str = Field(default="alias/doc-pipeline-s3", alias="S3_KMS_KEY_ID")
    stuck_job_older_than_seconds: int = Field(default=1800, alias="STUCK_JOB_OLDER_THAN_SECONDS")
    stuck_scan_interval_seconds: int = Field(default=60, alias="STUCK_SCAN_INTERVAL_SECONDS")
    webhook_timeout_seconds: float = Field(default=5.0, alias="WEBHOOK_TIMEOUT_SECONDS")
    webhook_max_attempts: int = Field(default=3, alias="WEBHOOK_MAX_ATTEMPTS")
    # Local demo fallback when tenants.config_json omits webhook_*; never commit real secrets.
    webhook_default_url: str = Field(default="", alias="WEBHOOK_DEFAULT_URL")
    webhook_default_secret: str = Field(default="", alias="WEBHOOK_DEFAULT_SECRET")

    @field_validator("jwt_public_key_pem", "jwt_private_key_pem", mode="before")
    @classmethod
    def unescape_jwt_pem_newlines(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if (stripped.startswith('"') and stripped.endswith('"')) or (
                stripped.startswith("'") and stripped.endswith("'")
            ):
                stripped = stripped[1:-1]
            return stripped.replace("\\n", "\n")
        return value

    @model_validator(mode="after")
    def load_jwt_pems_from_paths(self) -> Self:
        if self.jwt_public_key_path:
            public_path = Path(self.jwt_public_key_path)
            if public_path.is_file():
                self.jwt_public_key_pem = public_path.read_text(encoding="utf-8").strip()
        if self.jwt_private_key_path:
            private_path = Path(self.jwt_private_key_path)
            if private_path.is_file():
                self.jwt_private_key_pem = private_path.read_text(encoding="utf-8").strip()
        return self

    @field_validator("aws_endpoint_url", "virus_scan_url", "ocr_url", mode="before")
    @classmethod
    def empty_optional_string_is_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    # Compose/.env often has `OTEL_SDK_DISABLED=` (empty) — pydantic bool rejects "".
    @field_validator("otel_sdk_disabled", mode="before")
    @classmethod
    def empty_bool_is_false(cls, value: object) -> object:
        if value == "":
            return False
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
