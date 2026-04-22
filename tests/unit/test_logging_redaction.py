import io
import json
import logging

import structlog

from doc_pipeline.config.settings import Settings
from doc_pipeline.logging import configure_logging, reset_logging_for_tests


def _capture_log(settings: Settings) -> tuple[io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    configure_logging(settings)
    return stream, handler


def test_presigned_url_key_redacted() -> None:
    reset_logging_for_tests()
    settings = Settings(_env_file=None, log_level="INFO")
    stream, _handler = _capture_log(settings)
    logger = structlog.get_logger("test")
    logger.info(
        "presign issued",
        presigned_url="https://bucket.s3.amazonaws.com/key?X-Amz-Signature=secret",
    )
    payload = json.loads(stream.getvalue().strip())
    assert payload["presigned_url"] == "[REDACTED]"
    assert "X-Amz-Signature" not in stream.getvalue()


def test_https_query_value_redacted() -> None:
    reset_logging_for_tests()
    settings = Settings(_env_file=None, log_level="INFO")
    stream, _handler = _capture_log(settings)
    logger = structlog.get_logger("test")
    logger.info("upload", location="https://example.com/obj?sig=abc123&token=xyz")
    payload = json.loads(stream.getvalue().strip())
    assert payload["location"] == "[REDACTED]"
    assert "sig=abc123" not in stream.getvalue()


def test_http_query_presign_value_redacted() -> None:
    """LocalStack-style http:// URLs with query strings must redact (non-presigned key)."""
    reset_logging_for_tests()
    settings = Settings(_env_file=None, log_level="INFO")
    stream, _handler = _capture_log(settings)
    logger = structlog.get_logger("test")
    logger.info(
        "upload",
        location="http://localstack:4566/bucket/key?X-Amz-Signature=secret",
    )
    payload = json.loads(stream.getvalue().strip())
    assert payload["location"] == "[REDACTED]"
    assert "X-Amz-Signature" not in stream.getvalue()
    assert "secret" not in stream.getvalue()


def test_authorization_header_redacted() -> None:
    reset_logging_for_tests()
    settings = Settings(_env_file=None, log_level="INFO")
    stream, _handler = _capture_log(settings)
    logger = structlog.get_logger("test")
    logger.info("request", authorization="Bearer secret-token")
    payload = json.loads(stream.getvalue().strip())
    assert payload["authorization"] == "[REDACTED]"
