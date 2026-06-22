import pytest

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.hooks.adapters.http_ocr import HttpOcrHook
from doc_pipeline.domain.hooks.adapters.http_virus import HttpVirusScanHook
from doc_pipeline.domain.hooks.factory import build_hooks
from doc_pipeline.domain.hooks.stubs import StubVirusScanHook


def _base_settings(**overrides: object) -> Settings:
    defaults = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "aws_region": "eu-central-1",
        "s3_bucket": "b",
        "sqs_queue_url": "http://localhost/q",
        "sqs_dlq_url": "http://localhost/dlq",
        "jwt_public_key_pem": "-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----",
        "virus_hook_backend": "stub",
        "ocr_hook_backend": "stub",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_build_hooks_defaults_to_stubs() -> None:
    settings = _base_settings()
    virus, ocr, extract = build_hooks(settings)
    assert isinstance(virus, StubVirusScanHook)


def test_build_hooks_http_virus_when_configured() -> None:
    settings = _base_settings(
        virus_hook_backend="http",
        virus_scan_url="https://av.test/scan",
    )
    virus, _ocr, _extract = build_hooks(settings)
    assert isinstance(virus, HttpVirusScanHook)


def test_build_hooks_http_virus_requires_url() -> None:
    settings = _base_settings(virus_hook_backend="http", virus_scan_url=None)
    with pytest.raises(ValueError, match="VIRUS_SCAN_URL"):
        build_hooks(settings)


def test_build_hooks_http_ocr_when_configured() -> None:
    settings = _base_settings(
        ocr_hook_backend="http",
        ocr_url="https://ocr.test/run",
    )
    _virus, ocr, _extract = build_hooks(settings)
    assert isinstance(ocr, HttpOcrHook)


def test_build_hooks_http_ocr_requires_url() -> None:
    settings = _base_settings(ocr_hook_backend="http", ocr_url=None)
    with pytest.raises(ValueError, match="OCR_URL"):
        build_hooks(settings)
