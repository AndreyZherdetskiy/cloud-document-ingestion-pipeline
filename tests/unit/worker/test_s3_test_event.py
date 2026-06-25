"""S3 notification TestEvent must ACK without KeyError or status transitions."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from doc_pipeline.config.settings import Settings
from doc_pipeline.worker import ingestion_consumer
from doc_pipeline.worker.events import IgnorableSqsPayload, parse_s3_event_message
from doc_pipeline.worker.ingestion_consumer import run_once

S3_TEST_EVENT = {
    "Service": "Amazon S3",
    "Event": "s3:TestEvent",
    "Time": "2026-06-17T08:00:00.000Z",
    "Bucket": "dev-doc-pipeline",
    "RequestId": "req-1",
    "HostId": "host-1",
}


def _queue_depth(sqs: object, queue_url: str) -> int:
    attrs = sqs.get_queue_attributes(  # type: ignore[attr-defined]
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    return int(attrs["Attributes"]["ApproximateNumberOfMessages"])


def test_parse_s3_test_event_raises_ignorable_not_key_error() -> None:
    with pytest.raises(IgnorableSqsPayload):
        parse_s3_event_message(S3_TEST_EVENT)


def test_parse_s3_test_event_json_string() -> None:
    with pytest.raises(IgnorableSqsPayload):
        parse_s3_event_message(json.dumps(S3_TEST_EVENT))


def test_parse_s3_test_event_sns_wrapped() -> None:
    wrapped = {"Message": json.dumps(S3_TEST_EVENT)}
    with pytest.raises(IgnorableSqsPayload):
        parse_s3_event_message(wrapped)


@pytest.mark.asyncio
async def test_ingestion_run_once_deletes_test_event() -> None:
    with mock_aws():
        ingestion_consumer._stop.clear()
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="test-ingest-s3-testevent")["QueueUrl"]
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(S3_TEST_EVENT))
        settings = Settings(sqs_queue_url=queue_url, otel_sdk_disabled=True)
        factory = MagicMock()

        result = await run_once(
            sqs=sqs,
            session_factory=factory,
            settings=settings,
        )

        assert result is True
        assert _queue_depth(sqs, queue_url) == 0


@pytest.mark.asyncio
async def test_ingestion_run_once_keeps_message_on_parse_error() -> None:
    with mock_aws():
        ingestion_consumer._stop.clear()
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="test-ingest-bad-payload")["QueueUrl"]
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"bucket": "only-bucket"}))
        settings = Settings(sqs_queue_url=queue_url, otel_sdk_disabled=True)
        factory = MagicMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        ctx.__aexit__ = AsyncMock(return_value=None)
        factory.return_value = ctx

        with patch("doc_pipeline.worker.ingestion_consumer.delete_message") as delete_mock:
            result = await run_once(
                sqs=sqs,
                session_factory=factory,
                settings=settings,
            )

        assert result is True
        delete_mock.assert_not_called()
