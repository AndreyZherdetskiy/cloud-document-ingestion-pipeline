"""Live split-queue check — ingest vs processing SQS URLs when LocalStack is up."""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

from doc_pipeline.config.settings import get_settings
from doc_pipeline.infrastructure.aws.sqs import get_sqs_client

pytestmark = pytest.mark.integration

INGEST_QUEUE_NAME = "dev-document-ingestion"
PROCESSING_QUEUE_NAME = "dev-document-processing"

_SKIP_REASON = "LocalStack/Docker not reachable — deselected from make ci by default"


def _aws_endpoint_reachable() -> bool:
    settings = get_settings()
    endpoint = (settings.aws_endpoint_url or "http://localhost:4566").rstrip("/")
    try:
        urllib.request.urlopen(f"{endpoint}/_localstack/health", timeout=1)  # noqa: S310
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _live_sqs_requested() -> bool:
    return os.environ.get("DOC_PIPELINE_LIVE_SQS") == "1" or _aws_endpoint_reachable()


@pytest.mark.integration
def test_ingest_and_processing_queues_are_distinct() -> None:
    # Enqueue routing: tests/unit/worker/test_ingestion_enqueue.py
    if not _live_sqs_requested():
        pytest.skip(_SKIP_REASON)

    settings = get_settings()
    sqs = get_sqs_client(settings)

    ingest_url = sqs.get_queue_url(QueueName=INGEST_QUEUE_NAME)["QueueUrl"]
    processing_url = sqs.get_queue_url(QueueName=PROCESSING_QUEUE_NAME)["QueueUrl"]
    assert ingest_url != processing_url

    listed = sqs.list_queues(QueueNamePrefix="dev-document-")
    queue_urls = listed.get("QueueUrls", [])
    assert any(url.endswith(f"/{INGEST_QUEUE_NAME}") for url in queue_urls)
    assert any(url.endswith(f"/{PROCESSING_QUEUE_NAME}") for url in queue_urls)

    for queue_url in (ingest_url, processing_url):
        sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=1,
        )
