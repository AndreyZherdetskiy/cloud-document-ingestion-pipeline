"""Behavioral tests for seed check_queues (all four SQS URLs)."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from doc_pipeline.config.settings import Settings
from doc_pipeline.seed.common import check_queues

_MISSING_QUEUE = {
    "Error": {
        "Code": "AWS.SimpleQueueService.NonExistentQueue",
        "Message": "missing",
    }
}


class FakeSqs:
    """Recording SQS client: succeeds for allowlist URLs, else ClientError."""

    def __init__(
        self,
        *,
        ok_urls: set[str] | None = None,
        fail_urls: set[str] | None = None,
    ) -> None:
        self.ok_urls = ok_urls
        self.fail_urls = fail_urls or set()
        self.probed: list[str] = []

    def get_queue_attributes(self, *, QueueUrl: str, AttributeNames: list[str]) -> dict[str, Any]:
        self.probed.append(QueueUrl)
        if QueueUrl in self.fail_urls:
            raise ClientError(_MISSING_QUEUE, "GetQueueAttributes")
        if self.ok_urls is not None and QueueUrl not in self.ok_urls:
            raise ClientError(_MISSING_QUEUE, "GetQueueAttributes")
        return {"Attributes": {"QueueArn": f"arn:aws:sqs:local:{QueueUrl}"}}


@pytest.fixture
def four_queue_settings() -> Settings:
    return Settings(
        _env_file=None,
        otel_sdk_disabled=True,
        sqs_queue_url="http://localhost/ingest",
        sqs_dlq_url="http://localhost/ingest-dlq",
        sqs_processing_queue_url="http://localhost/processing",
        sqs_processing_dlq_url="http://localhost/processing-dlq",
    )


def test_check_queues_none_sqs_skips() -> None:
    settings = Settings(_env_file=None, otel_sdk_disabled=True)
    assert check_queues(None, settings) is True


def test_check_queues_all_four_ok(four_queue_settings: Settings) -> None:
    sqs = FakeSqs()
    assert check_queues(sqs, four_queue_settings) is True
    assert set(sqs.probed) == {
        four_queue_settings.sqs_queue_url,
        four_queue_settings.sqs_dlq_url,
        four_queue_settings.sqs_processing_queue_url,
        four_queue_settings.sqs_processing_dlq_url,
    }


def test_check_queues_processing_url_raises_false(four_queue_settings: Settings) -> None:
    sqs = FakeSqs(fail_urls={four_queue_settings.sqs_processing_queue_url})
    assert check_queues(sqs, four_queue_settings) is False
    assert four_queue_settings.sqs_processing_queue_url in sqs.probed


def test_check_queues_processing_dlq_raises_false(four_queue_settings: Settings) -> None:
    sqs = FakeSqs(fail_urls={four_queue_settings.sqs_processing_dlq_url})
    assert check_queues(sqs, four_queue_settings) is False
